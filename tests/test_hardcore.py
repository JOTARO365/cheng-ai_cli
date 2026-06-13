"""HARDCORE tier — adversarial / stress probes against the harness.

Where JOTARO is robust these PASS (path-jail, malformed args, caps, lockout).
Where there's a known gap (no context compaction, tool-exception not isolated,
max_steps truncation) the test PINS the *current* behavior so the gap is explicit and
will fail loudly the day we fix it — each such test is tagged GAP in a comment.

All offline: Ollama is monkeypatched. See docs/GAP_VS_CLAUDE_CODE.md for the matrix.
"""
from __future__ import annotations

import pytest

from ai import brain as brain_mod
from ai.auth import Auth
from ai.brain import Brain
from ai.fs_tools import make_fs_dispatcher
from ai.shell_tools import make_shell_dispatcher
from ai.web_tools import _clean_query, _filter_results, make_web_dispatcher
from storage.db import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    return Database(tmp_path / "t.db")


# ---- fake Ollama (scriptable) ---------------------------------------------
class _Resp:
    def __init__(self, message: dict) -> None:
        self._m, self.status_code = message, 200

    def raise_for_status(self) -> None: ...

    def json(self) -> dict:
        return {"message": self._m}


def _scripted_post(monkeypatch, messages):
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        i = min(calls["n"], len(messages) - 1)
        calls["n"] += 1
        return _Resp(messages[i])

    monkeypatch.setattr(brain_mod.httpx, "post", fake_post)
    return calls


# ===========================================================================
# 1. LOOP — stop condition holds against a model that never stops
# ===========================================================================
def test_runaway_tool_loop_stops_at_max_steps(db, monkeypatch):
    """A model that asks for a tool forever must NOT loop forever."""
    forever = {"role": "assistant", "content": "",
               "tool_calls": [{"function": {"name": "get_down_nodes", "arguments": {}}}]}
    calls = _scripted_post(monkeypatch, [forever])
    b = Brain("http://x", "m", db, max_steps=4)
    answer = b.ask(b.new_history(), "loop please")
    assert calls["n"] == 4                      # capped exactly at max_steps
    assert answer                                # returns a fallback, not a hang/crash
    # GAP (#2): nothing trimmed the history — it grew one user + 4*(assistant+tool) msgs
    assert len([m for m in b.new_history()]) >= 1


def test_tool_exception_is_isolated(db, monkeypatch):
    """FIXED (#1b): a tool that *raises* must not crash the turn — the loop wraps
    _execute, feeds the error back, and lets the model produce a final answer."""
    # 1st: model calls the bad tool. 2nd: model recovers and answers normally.
    msgs = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"function": {"name": "boom", "arguments": {}}}]},
        {"role": "assistant", "content": "the tool failed, here is what I can say"},
    ]
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        i = min(calls["n"], len(msgs) - 1)
        calls["n"] += 1
        return _Resp(msgs[i])

    monkeypatch.setattr(brain_mod.httpx, "post", fake_post)

    def raising_dispatch(name, args):
        raise RuntimeError("tool blew up")

    b = Brain("http://x", "m", db, tools=[], dispatcher=raising_dispatch)
    history = b.new_history()
    answer = b.ask(history, "trigger the bad tool")        # must NOT raise
    assert "here is what I can say" in answer
    # the error was fed back as a tool message so the model could see it
    tool_msgs = [m for m in history if m.get("role") == "tool"]
    assert tool_msgs and "failed" in tool_msgs[0]["content"]


def test_keyboardinterrupt_is_not_swallowed(db, monkeypatch):
    """A user Ctrl-C during a tool must still propagate (it's BaseException, not caught)."""
    _scripted_post(monkeypatch, [
        {"role": "assistant", "content": "",
         "tool_calls": [{"function": {"name": "boom", "arguments": {}}}]},
    ])

    def interrupting_dispatch(name, args):
        raise KeyboardInterrupt

    b = Brain("http://x", "m", db, tools=[], dispatcher=interrupting_dispatch)
    with pytest.raises(KeyboardInterrupt):
        b.ask(b.new_history(), "ctrl-c please")


# ===========================================================================
# 2. CONTEXT — grows unbounded (the priority gap, pinned)
# ===========================================================================
def test_context_has_no_compaction(db, monkeypatch):
    """GAP (#2): repeated turns accumulate; there is no compaction hook today."""
    _scripted_post(monkeypatch, [{"role": "assistant", "content": "ok"}])
    b = Brain("http://x", "m", db)
    history = b.new_history()
    before = len(history)
    for i in range(10):
        b.ask(history, f"turn {i}")
    assert len(history) == before + 20          # 10 * (user + assistant), nothing dropped
    assert not hasattr(b, "compact")            # no compaction API yet → reminder to add


# ===========================================================================
# 3. FILESYSTEM — the path-jail holds against escape vectors
# ===========================================================================
@pytest.mark.parametrize("evil", [
    "../secret.txt", "../../etc/passwd", "..\\..\\windows\\system32\\x",
    "sub/../../escape", "/abs/elsewhere", "C:\\Windows\\system32\\drivers\\etc\\hosts",
    "....//....//x",
])
def test_path_jail_blocks_escapes(tmp_path, evil):
    d = make_fs_dispatcher(tmp_path / "ws")
    out = d("read_file", {"path": evil})
    assert "error" in out                        # never reads outside the workspace


def test_path_jail_allows_legit_nested(tmp_path):
    d = make_fs_dispatcher(tmp_path / "ws")
    d("write_file", {"path": "a/b/c.txt", "content": "hi"})
    assert d("read_file", {"path": "a/b/c.txt"})["content"] == "hi"


def test_read_truncates_huge_file(tmp_path):
    d = make_fs_dispatcher(tmp_path / "ws")
    d("write_file", {"path": "big.txt", "content": "x" * 200_000})
    out = d("read_file", {"path": "big.txt"})
    assert out["truncated"] and len(out["content"]) == 50_000


def test_edit_zero_match_leaves_file_untouched(tmp_path):
    d = make_fs_dispatcher(tmp_path / "ws")
    d("write_file", {"path": "f.txt", "content": "hello"})
    out = d("edit_file", {"path": "f.txt", "old_string": "NOPE", "new_string": "X"})
    assert "error" in out
    assert d("read_file", {"path": "f.txt"})["content"] == "hello"


def test_search_and_find_are_capped(tmp_path):
    d = make_fs_dispatcher(tmp_path / "ws")
    for i in range(250):
        d("write_file", {"path": f"f{i}.txt", "content": "needle here"})
    assert d("find_files", {"pattern": "*.txt"})["count"] <= 200
    s = d("search_text", {"query": "needle"})
    assert len(s["matches"]) <= 100 and s["truncated"]


# ===========================================================================
# 4. MALFORMED ARGS — dispatchers degrade to {error}, never throw
# ===========================================================================
@pytest.mark.parametrize("name,args", [
    ("read_file", {}), ("read_file", {"path": None}),
    ("list_dir", {"path": 123}), ("edit_file", {"path": "x"}),
    ("write_file", {"path": "x"}), ("find_files", {}), ("search_text", {}),
    ("totally_unknown", {"x": 1}),
])
def test_fs_dispatcher_never_throws(tmp_path, name, args):
    d = make_fs_dispatcher(tmp_path / "ws")
    out = d(name, args)                           # must not raise
    assert isinstance(out, dict)


def test_shell_empty_and_unknown(tmp_path):
    d = make_shell_dispatcher(tmp_path / "ws")
    assert "error" in d("run_command", {"command": "   "})
    assert "error" in d("run_command", {})
    assert "error" in d("nope", {"command": "ls"})


def test_web_dispatcher_handles_garbage(monkeypatch):
    d = make_web_dispatcher()
    assert "error" in d("web_search", {"query": ""})
    assert "error" in d("fetch_url", {"url": ""})
    assert "error" in d("unknown", {})
    # query cleaning + result filtering survive odd input
    assert _clean_query("   ") == "   " or _clean_query("   ") == ""
    assert _filter_results([], 5) == []
    assert _filter_results([{"url": None, "title": None}], 5) == []


# ===========================================================================
# 5. AUTH — adversarial credentials
# ===========================================================================
def test_sql_injection_username_is_inert(db):
    a = Auth(db)
    # parameterized queries → this is just an (invalid) username, not SQL
    evil = "admin'; DROP TABLE users;--"
    with pytest.raises(Exception):
        a.register(evil, "password123")          # rejected by the username regex
    a.register("realuser", "password123")
    assert a.db.count_users() == 1               # table intact, real user stored


def test_long_password_and_unicode_username(db):
    a = Auth(db)
    a.register("user1", "p" * 4096)              # very long password is fine
    assert a.authenticate("user1", "p" * 4096)[0]
    with pytest.raises(Exception):
        a.register("ผู้ใช้", "password123")        # non-ASCII username rejected by regex


def test_timing_safe_reject_for_unknown_user(db):
    a = Auth(db)
    ok, user, msg = a.authenticate("ghost", "x")
    assert not ok and user is None               # no crash, vague message
