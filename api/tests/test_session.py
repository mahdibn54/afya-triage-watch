"""E6-2 demo sign-in session and E6-1a /login-as, /demo/users, /me (docs/api.md section 4). Real current_user here
(no dependency override): the user comes from the signed cookie, the role from afya.users."""
from __future__ import annotations

import pytest
from itsdangerous import URLSafeTimedSerializer

from afya_api import session

SECRET = "test-secret-0123456789abcdef"


@pytest.fixture
def demo(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("SESSION_SECRET", SECRET)
    client.cookies.clear()
    return client


def test_no_cookie_is_401_with_the_contract_error_body(demo):
    r = demo.get("/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_demo_users_lists_people_only(demo):
    r = demo.get("/demo/users")
    assert r.status_code == 200
    ids = {u["id"]: u["role"] for u in r.json()}
    assert ids["nurse-a"] == "nurse" and ids["clin-m"] == "clinician" and ids["mgr-k"] == "manager"
    assert "agent" not in ids and "system" not in ids


def test_login_sets_a_strict_httponly_cookie_and_me_reads_it(demo, conn):
    r = demo.post("/login-as", json={"user_id": "clin-m"})
    assert r.status_code == 200 and r.json() == {"id": "clin-m", "name": "Dr. M", "role": "clinician"}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{session.COOKIE}=") and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Path=/" in cookie
    assert demo.get("/me").json() == {"id": "clin-m", "name": "Dr. M", "role": "clinician", "demo": True}
    row = conn.execute("SELECT actor, auth, payload FROM audit_log WHERE kind = 'login' ORDER BY id DESC LIMIT 1"
                       ).fetchone()
    assert (row["actor"], row["auth"], row["payload"]) == ("clin-m", "demo_switcher", {"role": "clinician"})


@pytest.mark.parametrize("user_id", ["agent", "system", "nobody"])
def test_agent_system_and_unknown_cannot_sign_in(demo, user_id):
    r = demo.post("/login-as", json={"user_id": user_id})
    assert r.status_code == 404 and "set-cookie" not in r.headers


def test_body_cannot_choose_the_user_or_role(demo):
    demo.post("/login-as", json={"user_id": "mgr-k"})
    assert demo.post("/login-as", json={"user_id": "nurse-a", "role": "nurse"}).status_code == 422
    r = demo.post("/vitals", json={"visit_id": "v-x", "idempotency_key": "k", "user": "nurse-a", "heart_rate": 80})
    assert r.status_code == 422                       # extra fields are refused, the session stays the manager's
    assert demo.get("/me").json()["role"] == "manager"


def test_tampered_expired_or_foreign_cookies_are_401(demo, monkeypatch):
    good = session.sign("nurse-a")
    for bad in (good[:-2] + "xx",                                                    # tampered
                URLSafeTimedSerializer("another-secret-0123456789", salt=session.SALT).dumps({"uid": "nurse-a"}),
                URLSafeTimedSerializer(SECRET, salt="other-salt").dumps({"uid": "nurse-a"})):
        demo.cookies.set(session.COOKIE, bad)
        assert demo.get("/me").status_code == 401
    demo.cookies.set(session.COOKIE, good)
    assert demo.get("/me").status_code == 200
    monkeypatch.setattr(session, "MAX_AGE_S", -1)                                    # expired
    assert demo.get("/me").status_code == 401


def test_demo_mode_off_hides_sign_in_and_refuses_sessions(demo, monkeypatch):
    demo.post("/login-as", json={"user_id": "nurse-a"})
    monkeypatch.setenv("DEMO_MODE", "0")
    assert demo.post("/login-as", json={"user_id": "nurse-a"}).status_code == 404
    assert demo.get("/demo/users").status_code == 404
    assert demo.get("/me").status_code == 401                # an old demo cookie is worth nothing


@pytest.mark.parametrize("secret", ["", "short", "CHANGE_ME_long_random_string"])
def test_missing_or_example_secret_refuses_to_sign(demo, monkeypatch, secret):
    monkeypatch.setenv("SESSION_SECRET", secret)
    r = demo.post("/login-as", json={"user_id": "nurse-a"})
    assert r.status_code == 503 and "set-cookie" not in r.headers


def test_session_user_is_the_audit_actor_and_manager_is_refused(demo, conn, visit):
    demo.post("/login-as", json={"user_id": "mgr-k"})
    r = demo.post("/vitals", json={"visit_id": visit, "idempotency_key": "mgr-try-1", "heart_rate": 80})
    assert r.status_code == 403
    row = conn.execute("SELECT actor, auth FROM audit_log WHERE kind = 'record_vitals_refused' AND visit_id = %s "
                       "ORDER BY id DESC LIMIT 1", (visit,)).fetchone()
    assert row is not None and (row["actor"], row["auth"]) == ("mgr-k", "demo_switcher")
