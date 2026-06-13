"""Username/password login for CHENG AI — stdlib only, no external crypto dep.

Passwords are NEVER stored in plaintext. We keep a PBKDF2-HMAC-SHA256 hash with a
per-user random salt and compare in constant time (hmac.compare_digest). Repeated
wrong guesses trigger a temporary lockout to slow brute force. Everything lives in
the same offline SQLite store (*.db is gitignored — never commit it).

This module is pure policy + storage glue; the interactive prompts live in cheng.py
so the logic here stays unit-testable.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from storage.db import Database

# --- policy knobs ----------------------------------------------------------
_ALGO = "sha256"
_ITERATIONS = 200_000          # PBKDF2 rounds — slow enough to deter offline cracking
_SALT_BYTES = 16
MIN_PASSWORD_LEN = 6
MAX_FAILED = 5                 # wrong guesses before a lockout kicks in
LOCK_MINUTES = 15
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
VALID_ROLES = ("admin", "user")


@dataclass(frozen=True)
class User:
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return (hash_hex, salt_hex). A new random salt is generated if none is given."""
    salt_bytes = bytes.fromhex(salt) if salt else os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), salt_bytes, _ITERATIONS)
    return digest.hex(), salt_bytes.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    """Constant-time check of a candidate password against a stored hash."""
    try:
        calc, _ = hash_password(password, salt_hex)
    except ValueError:           # malformed salt hex
        return False
    return hmac.compare_digest(calc, hash_hex)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthError(ValueError):
    """User-facing problem (bad input, duplicate, etc.) — message is safe to show."""


class Auth:
    """Username/password gate backed by the SQLite `users` table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- registration / admin ----
    def has_users(self) -> bool:
        return self.db.count_users() > 0

    def register(self, username: str, password: str, role: str = "user") -> User:
        username = (username or "").strip()
        if not _USERNAME_RE.match(username):
            raise AuthError("username must be 3–32 chars: letters, digits, . _ -")
        if role not in VALID_ROLES:
            raise AuthError(f"role must be one of {', '.join(VALID_ROLES)}")
        if len(password or "") < MIN_PASSWORD_LEN:
            raise AuthError(f"password must be at least {MIN_PASSWORD_LEN} characters")
        if self.db.get_user(username) is not None:
            raise AuthError(f"user {username!r} already exists")
        pw_hash, salt = hash_password(password)
        self.db.create_user(username, pw_hash, salt, role)
        return User(username, role)

    # ---- login ----
    def authenticate(self, username: str, password: str) -> tuple[bool, User | None, str]:
        """Return (ok, user, message). On failure `user` is None and `message`
        explains why — kept deliberately vague about which half was wrong, except
        for lockout (where the user needs to know to wait)."""
        username = (username or "").strip()
        row = self.db.get_user(username)
        if row is None:
            return False, None, "invalid username or password"

        locked = self._locked_for(row)
        if locked is not None:
            return False, None, f"account locked — try again in {locked} min"

        if verify_password(password, row["pw_hash"], row["salt"]):
            self.db.touch_user_login(username)
            return True, User(username, row["role"]), "ok"

        # wrong password — bump the failure counter, lock past the threshold
        failed = int(row["failed"]) + 1
        locked_until = None
        if failed >= MAX_FAILED:
            locked_until = (_utcnow() + timedelta(minutes=LOCK_MINUTES)).isoformat(
                timespec="seconds")
            self.db.set_user_lock(username, 0, locked_until)   # reset count once locked
            return False, None, f"too many attempts — account locked for {LOCK_MINUTES} min"
        self.db.set_user_lock(username, failed, None)
        left = MAX_FAILED - failed
        return False, None, f"invalid username or password ({left} attempt(s) left)"

    def _locked_for(self, row: dict) -> int | None:
        """Minutes remaining on an active lock, or None if not locked."""
        lu = row.get("locked_until")
        if not lu:
            return None
        try:
            until = datetime.fromisoformat(lu)
        except ValueError:
            return None
        delta = (until - _utcnow()).total_seconds()
        return max(1, round(delta / 60)) if delta > 0 else None

    # ---- password change ----
    def change_password(self, username: str, old: str, new: str) -> User:
        row = self.db.get_user(username)
        if row is None:
            raise AuthError("no such user")
        if not verify_password(old, row["pw_hash"], row["salt"]):
            raise AuthError("current password is incorrect")
        if len(new or "") < MIN_PASSWORD_LEN:
            raise AuthError(f"new password must be at least {MIN_PASSWORD_LEN} characters")
        pw_hash, salt = hash_password(new)
        self.db.set_user_password(username, pw_hash, salt)
        return User(username, row["role"])

    # ---- admin helpers ----
    def reset_password(self, username: str, new: str) -> None:
        """Admin override — set a password without knowing the old one."""
        if self.db.get_user(username) is None:
            raise AuthError("no such user")
        if len(new or "") < MIN_PASSWORD_LEN:
            raise AuthError(f"password must be at least {MIN_PASSWORD_LEN} characters")
        pw_hash, salt = hash_password(new)
        self.db.set_user_password(username, pw_hash, salt)

    def delete_user(self, username: str) -> bool:
        return self.db.delete_user(username)

    def list_users(self) -> list[dict]:
        return self.db.list_users()
