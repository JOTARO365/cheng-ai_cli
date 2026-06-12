"""Configuration loading & validation for the SME IT Agent.

Loads settings from a local .env file (see .env.example). Fatal config problems
are raised loudly at startup via ConfigError rather than failing silently later.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional; env vars may be set by the OS/service
    pass


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _get(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    val = os.getenv(name, default)
    if required and not val:
        raise ConfigError(f"Missing required env var: {name}")
    return val


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _parse_targets(raw: str | None, nodes_file: Path) -> list[str]:
    """Ping targets come from PING_TARGETS (comma-separated) and/or data/nodes.txt
    (one host per line, '#' comments allowed). Duplicates are removed, order kept."""
    targets: list[str] = []
    if raw:
        targets.extend(t.strip() for t in raw.split(",") if t.strip())
    if nodes_file.exists():
        for line in nodes_file.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                targets.append(line)
    # de-dupe, preserve order
    seen: set[str] = set()
    return [t for t in targets if not (t in seen or seen.add(t))]


@dataclass(frozen=True)
class Config:
    # AI brain (local Ollama only)
    ollama_host: str
    ollama_model: str
    # Active Directory (read-only)
    ad_domain: str | None
    ldap_server: str | None
    ldap_bind_user: str | None
    ldap_bind_pass: str | None
    # Collectors
    ping_interval_sec: int
    ping_timeout_ms: int
    ping_targets: list[str]
    offline_alert_sec: int  # node offline longer than this (work hours) => alert
    # Storage
    db_path: Path
    # Alerts (all optional)
    alert_line_token: str | None
    alert_teams_webhook: str | None
    alert_email_smtp: str | None

    def masked(self) -> dict[str, object]:
        """Config for logging — secrets masked."""
        secret = {"ldap_bind_pass", "alert_line_token", "alert_teams_webhook", "alert_email_smtp"}
        out: dict[str, object] = {}
        for k, v in self.__dict__.items():
            out[k] = "***" if (k in secret and v) else v
        return out


def load_config(base_dir: Path | None = None) -> Config:
    base = base_dir or Path(__file__).resolve().parent
    db_path = Path(_get("DB_PATH", str(base / "data" / "itagent.db")))  # type: ignore[arg-type]
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        ollama_host=_get("OLLAMA_HOST", "http://127.0.0.1:11434"),  # type: ignore[arg-type]
        ollama_model=_get("OLLAMA_MODEL", "qwen2.5:3b"),  # type: ignore[arg-type]
        ad_domain=_get("AD_DOMAIN"),
        ldap_server=_get("LDAP_SERVER"),
        ldap_bind_user=_get("LDAP_BIND_USER"),
        ldap_bind_pass=_get("LDAP_BIND_PASS"),
        ping_interval_sec=_get_int("PING_INTERVAL_SEC", 45),
        ping_timeout_ms=_get_int("PING_TIMEOUT_MS", 1000),
        ping_targets=_parse_targets(_get("PING_TARGETS"), base / "data" / "nodes.txt"),
        offline_alert_sec=_get_int("OFFLINE_ALERT_SEC", 300),
        db_path=db_path,
        alert_line_token=_get("ALERT_LINE_TOKEN"),
        alert_teams_webhook=_get("ALERT_TEAMS_WEBHOOK"),
        alert_email_smtp=_get("ALERT_EMAIL_SMTP"),
    )


def setup_logging(base_dir: Path | None = None, level: int = logging.INFO) -> None:
    """Rotating file logs under ./logs/ + console. Idempotent.

    Forces stdout/stderr to UTF-8 so Thai and punctuation (—, …) don't turn into
    mojibake in the Windows console (cp874/cp437). See powershell-windows-encoding.
    """
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    root = logging.getLogger()
    if root.handlers:  # already configured
        return
    base = base_dir or Path(__file__).resolve().parent
    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file_h = RotatingFileHandler(
        log_dir / "itagent.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    console_h = logging.StreamHandler()
    console_h.setFormatter(fmt)

    root.setLevel(level)
    root.addHandler(file_h)
    root.addHandler(console_h)
