"""Real API roles, single-use commands, FHIR writes and database audit permissions."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import httpx
import psycopg
import pytest
from afya_api.mcp_client import ToolFailed
from afya_mcp import db, workflow
from conftest import ORANGE, run


def approve(proposal, ttl=timedelta(hours=1)):
    with db.connect() as conn:
        return str(workflow.approve_proposal(conn, str(proposal["id"]), "nurse-a", ttl=ttl)["command"]["id"])


async def execute(stack, command):
    return await stack.gw.act("raise_recheck_flag", {"command_id": command, "actor": "nurse-a"})


def test_manager_403_nurse_approval_double_click_409_and_gated_write(stack):
    visit, _, proposal = run(stack.proposal())
    stack.http.post("/login-as", json={"user_id": "mgr-k"}).raise_for_status()
    path = f"/proposals/{proposal['id']}/approve"
    body = {"colour": "ORANGE", "signs_kept": [], "override_reason": None}
    assert stack.http.post(path, json=body).status_code == 403
    stack.untouched(visit, "YELLOW")
    stack.http.post("/login-as", json={"user_id": "nurse-a"}).raise_for_status()
    barrier = Barrier(2)

    def click():
        with httpx.Client(base_url="http://api:8080", cookies=stack.http.cookies, timeout=30) as client:
            barrier.wait(timeout=5)
            return client.post(path, json=body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: click(), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    response = next(r for r in responses if r.status_code == 200)
    assert stack.http.post(path, json=body).status_code == 409
    command = response.json()["command_id"]
    for _ in range(100):
        row = stack.query("SELECT * FROM commands WHERE id=%s", (command,))[0]
        if row["done_at"]:
            break
        time.sleep(0.2)
    assert row["done_at"]
    assert len(stack.flags(visit)) == 1 and stack.colour(visit) == "ORANGE"
    assert len(stack.query("SELECT id FROM commands WHERE visit_id=%s", (visit,))) == 1
    rows = stack.query("SELECT kind,actor FROM audit_log WHERE visit_id=%s", (visit,))
    assert {"proposal_approved", "command_done"} <= {r["kind"] for r in rows}
    assert all(r["actor"] == "nurse-a" for r in rows if r["kind"] in {"proposal_approved", "command_done"})
    assert run(execute(stack, command))["status"] == "already_done"
    assert len(stack.flags(visit)) == 1


@pytest.mark.parametrize("reason", ["expired", "stale"])
def test_expired_and_stale_commands_cannot_write(stack, reason):
    async def check():
        visit, _, proposal = await stack.proposal()
        command = approve(proposal, timedelta(seconds=-1) if reason == "expired" else timedelta(hours=1))
        if reason == "stale":
            await stack.record(visit, ORANGE)
        result = await execute(stack, command)
        assert result["status"] == "refused", result
        assert not stack.flags(visit) and stack.colour(visit) == "YELLOW"
        row = stack.query("SELECT * FROM commands WHERE id=%s", (command,))[0]
        assert row["claimed_at"] is None and row["done_at"] is None
    run(check())


def test_lost_flag_response_retry_converges_to_one_flag(stack):
    async def check():
        visit, _, proposal = await stack.proposal()
        command = approve(proposal)
        stack.fault("lost_response", "POST", "/fhir/Flag", 1)
        with pytest.raises(ToolFailed):
            await execute(stack, command)
        assert stack.control.get("/control").json()["matched"] == 1
        assert len(stack.flags(visit)) == 1, "HAPI committed before the response was lost"
        row = stack.query("SELECT * FROM commands WHERE id=%s", (command,))[0]
        assert row["claimed_at"] and row["done_at"] is None
        result = await execute(stack, command)
        assert result["status"] == "done", result
        assert len(stack.flags(visit)) == 1 and stack.colour(visit) == "ORANGE"
        assert (await execute(stack, command))["status"] == "already_done"
        assert len(stack.query("SELECT id FROM audit_log WHERE visit_id=%s AND kind='command_done'", (visit,))) == 1
    run(check())


def test_audit_log_insert_allowed_but_mutations_denied(stack):
    with db.connect() as conn:
        row = conn.execute("INSERT INTO audit_log(kind,actor,auth,payload) "
                           "VALUES ('group_a','nurse-a','demo_switcher','{}') RETURNING id").fetchone()
        for sql in ["UPDATE audit_log SET kind='tampered' WHERE id=%s", "DELETE FROM audit_log WHERE id=%s"]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(sql, (row["id"],))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("TRUNCATE audit_log")
        assert conn.execute("SELECT kind, auth FROM audit_log WHERE id=%s", (row["id"],)).fetchone() == {
            "kind": "group_a", "auth": "demo_switcher"}


def test_unreviewed_superseded_proposal_stays_visible_until_acknowledged(stack):
    async def check():
        visit, _, old = await stack.proposal()
        await stack.record(visit, ORANGE)
        stack.http.post("/login-as", json={"user_id": "nurse-a"}).raise_for_status()
        rows = stack.http.get("/proposals", params={"status": "superseded"}).json()
        shown = next(p for p in rows if p["id"] == str(old["id"]))
        assert not shown["reviewed"] and "not_reviewed" in {n["code"] for n in shown["notices"]}
        response = stack.http.post(f"/proposals/{old['id']}/acknowledge")
        assert response.status_code == 200
        rows = stack.http.get("/proposals", params={"status": "superseded"}).json()
        assert str(old["id"]) not in {p["id"] for p in rows}
        stack.untouched(visit, "YELLOW")
    run(check())
