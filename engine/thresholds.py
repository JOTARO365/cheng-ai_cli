"""Tunable thresholds for the Rule Engine — the ONLY place these numbers live.

Changing any value here changes who gets paged, so it is treated as a live-system
change (see .claude/roles/role.md + the live-system-rollout-safety skill). Values can
also be overridden per-site via environment variables (config, not code) using
Thresholds.from_env(), so a deployment can be tuned without editing this file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import datetime


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Thresholds:
    # --- login failures (Windows Event ID 4625), correlated per user/host ---
    login_fail_log_max: int = 2       # 1-2 fails => log only
    login_fail_ai_min: int = 3        # 3-4 fails => escalate to AI for pattern analysis
    login_fail_alert_min: int = 5     # 5+  fails => alert IT now (skip the AI)
    login_fail_window_sec: int = 600  # only count fails within this rolling window

    # --- node offline (ping) ---
    node_offline_wait_sec: int = 120  # offline < 2 min => wait, take no action yet
    node_offline_alert_sec: int = 300  # offline >= 5 min (work hours) => alert

    # --- work hours (local time, 24h clock; Monday=0 .. Sunday=6) ---
    work_hours_start: int = 8
    work_hours_end: int = 18
    work_days: tuple[int, ...] = (0, 1, 2, 3, 4)

    @classmethod
    def from_env(cls) -> "Thresholds":
        """Build defaults, then apply any per-site env overrides."""
        base = cls()
        return replace(
            base,
            login_fail_ai_min=_env_int("TH_LOGIN_FAIL_AI", base.login_fail_ai_min),
            login_fail_alert_min=_env_int("TH_LOGIN_FAIL_ALERT", base.login_fail_alert_min),
            login_fail_window_sec=_env_int("TH_LOGIN_FAIL_WINDOW", base.login_fail_window_sec),
            node_offline_wait_sec=_env_int("TH_OFFLINE_WAIT", base.node_offline_wait_sec),
            node_offline_alert_sec=_env_int("TH_OFFLINE_ALERT", base.node_offline_alert_sec),
            work_hours_start=_env_int("TH_WORK_START", base.work_hours_start),
            work_hours_end=_env_int("TH_WORK_END", base.work_hours_end),
        )


def is_work_time(when: datetime, t: Thresholds) -> bool:
    """True if `when` (local time) falls within configured work days & hours."""
    return when.weekday() in t.work_days and t.work_hours_start <= when.hour < t.work_hours_end
