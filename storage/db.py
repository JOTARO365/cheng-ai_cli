"""SQLite persistence for the SME IT Agent.

ALL database access goes through this module (SQLite is single-writer).
Only parameterized queries — never string-format SQL. WAL mode is enabled so the
chat CLI can read while collectors write.

Tables
------
nodes  : current state of each monitored host (one row per host, upserted)
events : append-only log of raw signals / state changes from collectors
alerts : alerts the system decided to raise (and whether they were delivered)
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    host              TEXT PRIMARY KEY,
    status            TEXT NOT NULL,            -- up | down | unknown
    latency_ms        REAL,
    consecutive_fails INTEGER NOT NULL DEFAULT 0,
    last_seen         TEXT,                     -- last time it was 'up' (ISO8601 UTC)
    last_checked      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,                    -- ISO8601 UTC
    source    TEXT NOT NULL,                    -- ping | eventlog | wmi | ldap ...
    kind      TEXT NOT NULL,                    -- node_up | node_down | login_fail ...
    severity  TEXT NOT NULL,                    -- info | warning | critical
    host      TEXT,
    message   TEXT NOT NULL,
    data      TEXT                              -- optional JSON blob
);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_host ON events(host);

CREATE TABLE IF NOT EXISTS alerts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    severity  TEXT NOT NULL,
    title     TEXT NOT NULL,
    body      TEXT NOT NULL,
    channel   TEXT,                             -- line | teams | email (once sent)
    sent      INTEGER NOT NULL DEFAULT 0        -- 0 = pending, 1 = delivered
);
CREATE INDEX IF NOT EXISTS idx_alerts_sent ON alerts(sent);

CREATE TABLE IF NOT EXISTS memory (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts    TEXT NOT NULL,
    kind  TEXT NOT NULL DEFAULT 'fact',      -- fact | correction | preference
    text  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,          -- e.g. 20260613-143002 (one chat session)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    label       TEXT,                       -- first user message (shown when listing)
    history     TEXT NOT NULL,              -- JSON array of chat messages
    seq         INTEGER NOT NULL DEFAULT 0  -- monotonic save counter (drives "latest")
);

CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    pw_hash       TEXT NOT NULL,             -- PBKDF2-HMAC-SHA256 hex (never plaintext)
    salt          TEXT NOT NULL,             -- per-user random salt, hex
    role          TEXT NOT NULL DEFAULT 'user',   -- admin | user
    created_at    TEXT NOT NULL,
    last_login    TEXT,
    failed        INTEGER NOT NULL DEFAULT 0,      -- consecutive failed logins
    locked_until  TEXT                             -- ISO8601 UTC; NULL = not locked
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class NodeState:
    host: str
    status: str
    latency_ms: float | None
    consecutive_fails: int
    last_seen: str | None
    last_checked: str


class Database:
    """Thin wrapper over a single SQLite file. Construct once, share the instance."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # migration: add sessions.seq to DBs created before it existed, THEN index it
            # (the index must come after the column exists for older tables to upgrade).
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
            if "seq" not in cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_seq ON sessions(seq)")

    # ---- nodes -----------------------------------------------------------
    def get_node(self, host: str) -> NodeState | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE host = ?", (host,)).fetchone()
        return _row_to_node(row) if row else None

    def list_nodes(self, status: str | None = None) -> list[NodeState]:
        sql = "SELECT * FROM nodes"
        params: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY host"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_node(r) for r in rows]

    def upsert_node(
        self,
        host: str,
        status: str,
        latency_ms: float | None,
        consecutive_fails: int,
        last_seen: str | None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO nodes (host, status, latency_ms, consecutive_fails,
                                   last_seen, last_checked)
                VALUES (:host, :status, :latency_ms, :fails, :last_seen, :checked)
                ON CONFLICT(host) DO UPDATE SET
                    status            = excluded.status,
                    latency_ms        = excluded.latency_ms,
                    consecutive_fails = excluded.consecutive_fails,
                    last_seen         = excluded.last_seen,
                    last_checked      = excluded.last_checked
                """,
                {
                    "host": host,
                    "status": status,
                    "latency_ms": latency_ms,
                    "fails": consecutive_fails,
                    "last_seen": last_seen,
                    "checked": utcnow(),
                },
            )

    # ---- events ----------------------------------------------------------
    def record_event(
        self,
        source: str,
        kind: str,
        severity: str,
        message: str,
        host: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO events (ts, source, kind, severity, host, message, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utcnow(),
                    source,
                    kind,
                    severity,
                    host,
                    message,
                    # default=str so odd types (datetime, Path) never break a write
                    json.dumps(data, ensure_ascii=False, default=str) if data else None,
                ),
            )
            return int(cur.lastrowid)

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- alerts ----------------------------------------------------------
    def record_alert(self, severity: str, title: str, body: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO alerts (ts, severity, title, body) VALUES (?, ?, ?, ?)",
                (utcnow(), severity, title, body),
            )
            return int(cur.lastrowid)

    def mark_alert_sent(self, alert_id: int, channel: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE alerts SET sent = 1, channel = ? WHERE id = ?",
                (channel, alert_id),
            )

    # ---- memory (things the user told the agent to remember) -------------
    def add_memory(self, text: str, kind: str = "fact") -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO memory (ts, kind, text) VALUES (?, ?, ?)",
                (utcnow(), kind, text.strip()),
            )
            return int(cur.lastrowid)

    def recent_memory(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, ts, kind, text FROM memory ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def search_memory(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Keyword-overlap search (memory is small for an SME). Returns the best
        matches; empty list if nothing overlaps. Vector recall is a later upgrade."""
        words = {w for w in query.lower().split() if len(w) > 1}
        if not words:
            return []
        scored = []
        for m in self.recent_memory(200):
            hits = sum(1 for w in words if w in m["text"].lower())
            if hits:
                scored.append((hits, m))
        scored.sort(key=lambda x: (-x[0], -x[1]["id"]))
        return [m for _, m in scored[:limit]]

    def forget_memory(self, mem_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM memory WHERE id = ?", (mem_id,))

    # ---- chat sessions (persistence / --continue / --resume) --------------
    # The whole conversation history is stored as one JSON blob keyed by session id.
    # Single-user CLI, sessions are small → blob-per-session beats a per-message table.
    def save_session(self, session_id: str, history: list[dict[str, Any]],
                     label: str | None = None) -> None:
        """Upsert a session's full history. `label` (set once, on first save) is the
        first user message, shown when listing. Re-saves only bump updated_at + history."""
        blob = json.dumps(history, ensure_ascii=False, default=str)
        now = utcnow()
        # `seq` is a monotonic counter (not the wall clock, which ties under a coarse
        # OS clock) so a just-saved session is always the latest --continue resumes.
        nxt = "(SELECT COALESCE(MAX(seq), 0) + 1 FROM sessions)"
        with self._conn() as conn:
            conn.execute(
                f"""INSERT INTO sessions (id, created_at, updated_at, label, history, seq)
                   VALUES (?, ?, ?, ?, ?, {nxt})
                   ON CONFLICT(id) DO UPDATE SET
                       updated_at = excluded.updated_at,
                       label      = COALESCE(sessions.label, excluded.label),
                       history    = excluded.history,
                       seq        = {nxt}""",
                (session_id, now, now, label, blob),
            )

    def load_session(self, session_id: str) -> list[dict[str, Any]] | None:
        """Return the stored history list, or None if no such session."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT history FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return json.loads(row["history"]) if row else None

    def latest_session_id(self) -> str | None:
        """Most recently updated session id (what `--continue` resumes), or None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM sessions ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return row["id"] if row else None

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, created_at, updated_at, label FROM sessions "
                "ORDER BY seq DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # ---- users (username/password login) ---------------------------------
    # Storage only — hashing / lockout policy lives in ai/auth.py. We keep the
    # hash + salt here, never a plaintext password.
    def create_user(self, username: str, pw_hash: str, salt: str,
                    role: str = "user") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO users (username, pw_hash, salt, role, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, pw_hash, salt, role, utcnow()),
            )

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        """Public view — no hash/salt. Admins first, then alphabetical."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT username, role, created_at, last_login FROM users "
                "ORDER BY (role = 'admin') DESC, username"
            ).fetchall()
        return [dict(r) for r in rows]

    def count_users(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])

    def delete_user(self, username: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
            return cur.rowcount > 0

    def set_user_password(self, username: str, pw_hash: str, salt: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET pw_hash = ?, salt = ?, failed = 0, locked_until = NULL "
                "WHERE username = ?",
                (pw_hash, salt, username),
            )

    def touch_user_login(self, username: str) -> None:
        """Record a successful login: stamp time, clear the failure/lock counters."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET last_login = ?, failed = 0, locked_until = NULL "
                "WHERE username = ?",
                (utcnow(), username),
            )

    def set_user_lock(self, username: str, failed: int,
                      locked_until: str | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET failed = ?, locked_until = ? WHERE username = ?",
                (failed, locked_until, username),
            )

    # ---- snapshot reads (the "tools" the chatbot answers from) ------------
    # These are READ-ONLY and return plain JSON-ready dicts so the FastAPI tool
    # server can hand them straight to Open WebUI. They are the single source the
    # chatbot uses to answer IT's questions — never let it guess outside these.
    def down_nodes(self) -> list[dict[str, Any]]:
        """Hosts currently 'down', newest-outage-first, with how long they've been
        offline (computed from last_seen). Nodes never seen 'up' report None."""
        out: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for n in self.list_nodes(status="down"):
            offline_min: float | None = None
            if n.last_seen:
                try:
                    offline_min = round(
                        (now - datetime.fromisoformat(n.last_seen)).total_seconds() / 60, 1
                    )
                except ValueError:
                    offline_min = None
            out.append(
                {
                    "host": n.host,
                    "consecutive_fails": n.consecutive_fails,
                    "last_seen": n.last_seen,
                    "offline_minutes": offline_min,
                }
            )
        out.sort(key=lambda d: (d["offline_minutes"] is None, -(d["offline_minutes"] or 0)))
        return out

    def _events_since(self, kind: str, hours: int) -> list[dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(
            timespec="seconds"
        )
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE kind = ? AND ts >= ? ORDER BY id DESC",
                (kind, cutoff),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _data(row: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads(row["data"]) if row.get("data") else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def login_fails(self, hours: int = 24) -> list[dict[str, Any]]:
        """Login-failure activity in the last `hours`, one row per user — the peak
        fail count seen and which host/IP it came from. Useful for 'login fail
        วันนี้มีกี่ครั้ง' / 'ใคร login พลาดเยอะ'."""
        by_user: dict[str, dict[str, Any]] = {}
        for row in self._events_since("login_fail", hours):
            d = self._data(row)
            user = str(d.get("user", "?"))
            count = int(d.get("count", 1))
            cur = by_user.get(user)
            if cur is None or count > cur["count"]:
                by_user[user] = {
                    "user": user,
                    "count": count,
                    "host": row.get("host") or d.get("host"),
                    "ip": d.get("ip"),
                    "last_ts": row.get("ts"),
                }
        return sorted(by_user.values(), key=lambda d: -d["count"])

    def locked_accounts(self, hours: int = 24) -> list[dict[str, Any]]:
        """Accounts that hit a lockout (Event 4740) in the last `hours`. NOTE: this
        reflects lockout *events*, not current AD state — we don't track unlocks in
        Phase 1, so report it as 'was locked', not 'is locked'."""
        seen: dict[str, dict[str, Any]] = {}
        for row in self._events_since("account_lockout", hours):
            d = self._data(row)
            user = str(d.get("user", "?"))
            if user not in seen:
                seen[user] = {"user": user, "host": row.get("host"), "ts": row.get("ts")}
        return list(seen.values())

    def recent_alerts(self, limit: int = 10) -> list[dict[str, Any]]:
        """Most recent alerts the system raised (newest first)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, ts, severity, title, body, channel, sent "
                "FROM alerts ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def system_summary(self) -> dict[str, Any]:
        """One-glance health: node counts by status + today's fail/lockout/alert
        tallies. The chatbot's answer to 'สถานะระบบตอนนี้เป็นยังไง'."""
        nodes = self.list_nodes()
        by_status: dict[str, int] = {}
        for n in nodes:
            by_status[n.status] = by_status.get(n.status, 0) + 1
        with self._conn() as conn:
            pending = conn.execute(
                "SELECT COUNT(*) AS c FROM alerts WHERE sent = 0"
            ).fetchone()["c"]
        return {
            "generated_at": utcnow(),
            "nodes_total": len(nodes),
            "nodes_up": by_status.get("up", 0),
            "nodes_down": by_status.get("down", 0),
            "nodes_unknown": by_status.get("unknown", 0),
            "login_fail_users_24h": len(self.login_fails(24)),
            "locked_accounts_24h": len(self.locked_accounts(24)),
            "alerts_pending": int(pending),
        }


def _row_to_node(row: sqlite3.Row) -> NodeState:
    return NodeState(
        host=row["host"],
        status=row["status"],
        latency_ms=row["latency_ms"],
        consecutive_fails=row["consecutive_fails"],
        last_seen=row["last_seen"],
        last_checked=row["last_checked"],
    )
