"""Tests for the username/password login (ai/auth.py + the users DB layer)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai.auth import (Auth, AuthError, MAX_FAILED, MIN_PASSWORD_LEN, User,
                     hash_password, verify_password)
from storage.db import Database


@pytest.fixture()
def auth(tmp_path):
    return Auth(Database(tmp_path / "t.db"))


# ---- hashing ----
def test_hash_is_salted_and_not_plaintext():
    h1, s1 = hash_password("hunter2")
    h2, s2 = hash_password("hunter2")
    assert s1 != s2 and h1 != h2          # random salt → different hashes
    assert "hunter2" not in h1            # never the plaintext
    assert verify_password("hunter2", h1, s1)
    assert not verify_password("wrong", h1, s1)


def test_verify_with_bad_salt_is_false():
    assert not verify_password("x", "deadbeef", "nothex!!")


# ---- registration ----
def test_register_and_authenticate(auth):
    auth.register("alice", "s3cret!", role="admin")
    ok, user, msg = auth.authenticate("alice", "s3cret!")
    assert ok and user == User("alice", "admin") and user.is_admin


def test_register_rejects_bad_input(auth):
    with pytest.raises(AuthError):
        auth.register("ab", "longenough")            # username too short
    with pytest.raises(AuthError):
        auth.register("bob", "x" * (MIN_PASSWORD_LEN - 1))  # password too short
    with pytest.raises(AuthError):
        auth.register("bob", "goodpass", role="root")       # bad role
    auth.register("bob", "goodpass")
    with pytest.raises(AuthError):
        auth.register("bob", "goodpass")             # duplicate


def test_has_users(auth):
    assert not auth.has_users()
    auth.register("admin", "password", role="admin")
    assert auth.has_users()


# ---- login failures / lockout ----
def test_wrong_password_reports_attempts_left(auth):
    auth.register("carol", "correcthorse")
    ok, user, msg = auth.authenticate("carol", "nope")
    assert not ok and user is None and "attempt" in msg


def test_unknown_user_is_vague(auth):
    ok, user, msg = auth.authenticate("ghost", "whatever")
    assert not ok and "invalid username or password" in msg


def test_lockout_after_max_failed(auth):
    auth.register("dave", "rightpass")
    for _ in range(MAX_FAILED):
        auth.authenticate("dave", "wrong")
    # even the CORRECT password is refused while locked
    ok, user, msg = auth.authenticate("dave", "rightpass")
    assert not ok and "locked" in msg


def test_successful_login_clears_failures(auth):
    auth.register("erin", "rightpass")
    auth.authenticate("erin", "wrong")
    auth.authenticate("erin", "wrong")
    ok, _, _ = auth.authenticate("erin", "rightpass")
    assert ok
    assert auth.db.get_user("erin")["failed"] == 0


def test_expired_lock_lets_user_back_in(auth):
    auth.register("frank", "rightpass")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    auth.db.set_user_lock("frank", 0, past)          # a lock that already elapsed
    ok, _, _ = auth.authenticate("frank", "rightpass")
    assert ok


# ---- password change ----
def test_change_password(auth):
    auth.register("gwen", "oldpass1")
    auth.change_password("gwen", "oldpass1", "newpass2")
    assert auth.authenticate("gwen", "newpass2")[0]
    assert not auth.authenticate("gwen", "oldpass1")[0]


def test_change_password_wrong_old(auth):
    auth.register("hank", "oldpass1")
    with pytest.raises(AuthError):
        auth.change_password("hank", "WRONG", "newpass2")


# ---- admin helpers ----
def test_reset_and_delete(auth):
    auth.register("ivy", "oldpass1")
    auth.reset_password("ivy", "freshpass")          # no old password needed
    assert auth.authenticate("ivy", "freshpass")[0]
    assert auth.delete_user("ivy")
    assert not auth.delete_user("ivy")               # already gone
    assert auth.db.get_user("ivy") is None


def test_list_users_hides_secrets(auth):
    auth.register("admin", "password", role="admin")
    auth.register("user1", "password")
    rows = auth.list_users()
    assert rows[0]["username"] == "admin"            # admins first
    assert all("pw_hash" not in r and "salt" not in r for r in rows)
