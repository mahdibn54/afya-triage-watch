"""E6-2: demo sign-in session. DEMO_MODE=1 only; there is no other sign-in (real sign-in is a stated gap).

The cookie holds only the user id, signed with SESSION_SECRET (itsdangerous, with an expiry). The role and the name are
always read from afya.users on each request, so a cookie can never carry a role. HttpOnly, SameSite=Strict, Path=/.
Secure is off by default because the demo is served over http://127.0.0.1:3000; set SESSION_COOKIE_SECURE=1 behind
HTTPS.
"""
from __future__ import annotations

import os

from afya_mcp import db
from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE = "afya_session"
MAX_AGE_S = 12 * 3600          # one shift
SALT = "afya-demo-session"
HUMAN_ROLES = ("nurse", "clinician", "manager")   # agent and system exist in afya.users but never sign in
MIN_SECRET_LEN = 16


class SessionUnavailable(Exception):
    """SESSION_SECRET is missing or too short: sessions are refused rather than signed with a weak key."""


def _serializer() -> URLSafeTimedSerializer:
    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < MIN_SECRET_LEN or secret.startswith("CHANGE_ME"):
        raise SessionUnavailable("SESSION_SECRET is not set (at least 16 characters, not the example value)")
    return URLSafeTimedSerializer(secret, salt=SALT)


def sign(user_id: str) -> str:
    return _serializer().dumps({"uid": user_id})


def user_id_from(cookie: str | None) -> str | None:
    """The user id in a valid, unexpired cookie; None otherwise (missing, tampered, expired, other secret)."""
    if not cookie:
        return None
    try:
        data = _serializer().loads(cookie, max_age=MAX_AGE_S)
    except BadSignature:   # SignatureExpired is a subclass
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, str) else None


def load_user(user_id: str) -> dict | None:
    """id, name, role of a person who may sign in (nurse, clinician, manager), from afya.users."""
    with db.connect() as conn:
        return conn.execute("SELECT id, name, role FROM users WHERE id = %s AND role = ANY(%s)",
                            (user_id, list(HUMAN_ROLES))).fetchone()


def demo_users() -> list[dict]:
    with db.connect() as conn:
        return conn.execute("SELECT id, name, role FROM users WHERE role = ANY(%s) ORDER BY "
                            "array_position(%s, role), id", (list(HUMAN_ROLES), list(HUMAN_ROLES))).fetchall()


def cookie_secure() -> bool:
    return os.environ.get("SESSION_COOKIE_SECURE") == "1"
