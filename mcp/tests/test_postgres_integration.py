"""Integration tests for the Postgres layer (db.py, workflow.py) against the running database, as afya_app.

Set DATABASE_URL to an afya_app URL that reaches the compose Postgres (the service publishes no port; use the
container address, see the README). Skipped when it is not set or not reachable. afya_app cannot DELETE, so every
test uses fresh ids and leaves its rows behind (dev database only).
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import timedelta

import psycopg
import pytest

from afya_mcp import db, workflow
from afya_mcp.workflow import Conflict, Forbidden

pytestmark = pytest.mark.integration


def _reachable() -> bool:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except psycopg.Error:
        return False


if not _reachable():
    pytest.skip("DATABASE_URL not set or Postgres not reachable", allow_module_level=True)


@pytest.fixture
def conn():
    with db.connect() as c:
        yield c


def new_id(prefix="t"):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def make_proposal(conn, visit=None, obs="o1", trigger="colour_rise", signs=(), colour="ORANGE"):
    visit = visit or new_id("v")
    db.upsert_visit(conn, visit, "p1", obs)
    p = workflow.insert_proposal(conn, visit, trigger, obs, workflow.evidence_hash([obs], signs, "r1"),
                                 {"to_colour": colour})
    assert p is not None
    return p


def approved_command(conn):
    p = make_proposal(conn)
    return workflow.approve_proposal(conn, str(p["id"]), "nurse-a")["command"]


def audit_kinds(conn, visit):
    return [r["kind"] for r in conn.execute("SELECT kind FROM audit_log WHERE visit_id = %s ORDER BY id", (visit,))]


# ---------- E4-2: visits ----------

def test_upsert_visit_creates_then_moves_latest(conn):
    v = new_id("v")
    db.upsert_visit(conn, v, "p9", "o1")
    db.upsert_visit(conn, v, "p9", "o2")
    row = conn.execute("SELECT * FROM visits WHERE id = %s", (v,)).fetchone()
    assert (row["patient_id"], row["latest_obs_id"]) == ("p9", "o2")


def test_store_wrapper_writes_through_its_own_connection():
    v = new_id("v")
    db.PgVisitStore().record_reading(v, "p9", "o7")
    with db.connect() as c:
        assert c.execute("SELECT latest_obs_id FROM visits WHERE id = %s", (v,)).fetchone()["latest_obs_id"] == "o7"


def test_newer_vitals_supersede_pending_and_keep_it_unreviewed(conn):
    p = make_proposal(conn, obs="o1")
    db.upsert_visit(conn, p["visit_id"], "p1", "o2")
    row = conn.execute("SELECT status, reviewed FROM proposals WHERE id = %s", (p["id"],)).fetchone()
    assert (row["status"], row["reviewed"]) == ("superseded", False)
    assert workflow.acknowledge(conn, str(p["id"]), "nurse-a") is True
    assert workflow.acknowledge(conn, str(p["id"]), "nurse-a") is False
    assert conn.execute("SELECT reviewed FROM proposals WHERE id = %s", (p["id"],)).fetchone()["reviewed"] is True


def test_reading_for_the_same_obs_does_not_supersede(conn):
    p = make_proposal(conn, obs="o1")
    db.upsert_visit(conn, p["visit_id"], "p1", "o1")
    assert conn.execute("SELECT status FROM proposals WHERE id = %s", (p["id"],)).fetchone()["status"] == "pending"


# ---------- E3-6: dedup ----------

def test_evidence_hash_is_order_independent_and_ignores_text():
    a = workflow.evidence_hash(["o2", "o1"], ["SOB_ACUTE", "CHEST_PAIN"], "r1")
    assert a == workflow.evidence_hash(["o1", "o2", "o1"], ["CHEST_PAIN", "SOB_ACUTE"], "r1")
    assert a != workflow.evidence_hash(["o1", "o2"], ["CHEST_PAIN"], "r1")
    assert a != workflow.evidence_hash(["o1", "o2"], ["CHEST_PAIN", "SOB_ACUTE"], "r2")
    assert len(a) == 64


def test_insert_proposal_dedups_on_visit_trigger_evidence(conn):
    p = make_proposal(conn)
    v, h, red = p["visit_id"], p["evidence_hash"], {"to_colour": "RED"}
    assert workflow.insert_proposal(conn, v, p["trigger"], "o1", h, red) is None
    assert workflow.insert_proposal(conn, v, "sign", "o1", h, red) is not None
    assert conn.execute("SELECT count(*) AS n FROM proposals WHERE visit_id = %s", (v,)).fetchone()["n"] == 2


def test_concurrent_identical_inserts_create_one_row(conn):
    v = new_id("v")
    db.upsert_visit(conn, v, "p1", "o1")
    results: list = []

    def go():
        with db.connect() as c:
            results.append(workflow.insert_proposal(c, v, "colour_rise", "o1", "same-hash", {"to_colour": "RED"}))

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r is None for r in results) == [False, True]


def test_supersede_pending_counts_only_older_pending(conn):
    p = make_proposal(conn, obs="o1")
    assert workflow.supersede_pending(conn, p["visit_id"], "o1") == 0
    assert workflow.supersede_pending(conn, p["visit_id"], "o2") == 1
    assert workflow.supersede_pending(conn, p["visit_id"], "o2") == 0


# ---------- E3-5: approve ----------

def test_approve_writes_decision_command_and_audit_together(conn):
    p = make_proposal(conn, colour="RED")
    out = workflow.approve_proposal(conn, str(p["id"]), "clin-m")
    assert out["proposal"]["status"] == "approved" and out["proposal"]["decided_by"] == "clin-m"
    cmd = out["command"]
    assert (cmd["visit_id"], cmd["obs_id"], cmd["colour"], cmd["evidence_hash"]) == (
        p["visit_id"], "o1", "RED", p["evidence_hash"])
    assert cmd["claimed_at"] is None and cmd["attempts"] == 0
    assert audit_kinds(conn, p["visit_id"]) == ["proposal_approved"]


def test_manager_and_agent_cannot_approve(conn):
    p = make_proposal(conn)
    for user in ("mgr-k", "agent"):
        with pytest.raises(Forbidden):
            workflow.approve_proposal(conn, str(p["id"]), user)
    with pytest.raises(Forbidden):
        workflow.approve_proposal(conn, str(p["id"]), "nobody")
    assert conn.execute("SELECT status FROM proposals WHERE id = %s", (p["id"],)).fetchone()["status"] == "pending"
    assert conn.execute("SELECT count(*) AS n FROM commands WHERE proposal_id = %s", (p["id"],)).fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE kind = 'approve_refused' "
                        "AND payload->>'proposal_id' = %s", (str(p["id"]),)).fetchone()["n"] == 2


def test_second_approve_is_a_conflict_and_logged(conn):
    p = make_proposal(conn)
    workflow.approve_proposal(conn, str(p["id"]), "nurse-a")
    with pytest.raises(Conflict):
        workflow.approve_proposal(conn, str(p["id"]), "clin-m")
    assert conn.execute("SELECT count(*) AS n FROM commands WHERE proposal_id = %s", (p["id"],)).fetchone()["n"] == 1
    assert conn.execute("SELECT count(*) AS n FROM audit_log WHERE kind = 'approve_refused' "
                        "AND payload->>'reason' = 'not pending' AND payload->>'proposal_id' = %s",
                        (str(p["id"]),)).fetchone()["n"] == 1


def test_approve_unknown_or_superseded_proposal_is_a_conflict(conn):
    with pytest.raises(Conflict):
        workflow.approve_proposal(conn, str(uuid.uuid4()), "nurse-a")
    p = make_proposal(conn, obs="o1")
    db.upsert_visit(conn, p["visit_id"], "p1", "o2")
    with pytest.raises(Conflict):
        workflow.approve_proposal(conn, str(p["id"]), "nurse-a")


def test_failed_command_insert_rolls_back_the_decision(conn):
    p = make_proposal(conn)
    conn.execute("UPDATE proposals SET payload = '{}' WHERE id = %s", (p["id"],))     # no to_colour: insert fails
    with pytest.raises(KeyError):
        workflow.approve_proposal(conn, str(p["id"]), "nurse-a")
    assert conn.execute("SELECT status FROM proposals WHERE id = %s", (p["id"],)).fetchone()["status"] == "pending"


def test_concurrent_double_approve_exactly_one_wins(conn):
    p = make_proposal(conn)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def go(user):
        with db.connect() as c:
            barrier.wait()
            try:
                workflow.approve_proposal(c, str(p["id"]), user)
                outcomes.append("ok")
            except Conflict:
                outcomes.append("conflict")

    threads = [threading.Thread(target=go, args=(u,)) for u in ("nurse-a", "clin-m")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(outcomes) == ["conflict", "ok"]
    assert conn.execute("SELECT count(*) AS n FROM commands WHERE proposal_id = %s", (p["id"],)).fetchone()["n"] == 1


def test_database_guard_blocks_redeciding_and_manager_approval(conn):
    p = make_proposal(conn)
    with pytest.raises(psycopg.Error):
        conn.execute("UPDATE proposals SET status = 'approved', decided_by = 'mgr-k' WHERE id = %s", (p["id"],))
    with pytest.raises(psycopg.Error):
        conn.execute("UPDATE proposals SET status = 'approved' WHERE id = %s", (p["id"],))
    workflow.approve_proposal(conn, str(p["id"]), "nurse-a")
    with pytest.raises(psycopg.Error):
        conn.execute("UPDATE proposals SET status = 'rejected' WHERE id = %s", (p["id"],))
    with pytest.raises(psycopg.Error):
        conn.execute("UPDATE proposals SET decided_by = 'clin-m' WHERE id = %s", (p["id"],))


# ---------- E3-5: claim ----------

def test_claim_succeeds_once(conn):
    c = approved_command(conn)
    claimed = workflow.claim_command(conn, str(c["id"]))
    assert claimed["attempts"] == 1 and claimed["claimed_at"] is not None
    assert workflow.claim_command(conn, str(c["id"])) is None


def test_claim_fails_when_newer_vitals_arrived(conn):
    c = approved_command(conn)
    db.upsert_visit(conn, c["visit_id"], "p1", "o2")
    assert workflow.claim_command(conn, str(c["id"])) is None


def test_claim_fails_when_expired(conn):
    p = make_proposal(conn)
    c = workflow.approve_proposal(conn, str(p["id"]), "nurse-a", ttl=timedelta(seconds=-1))["command"]
    assert workflow.claim_command(conn, str(c["id"])) is None


def test_claim_fails_when_proposal_is_not_approved(conn):
    p = make_proposal(conn)
    conn.execute("INSERT INTO commands (proposal_id, visit_id, obs_id, colour, evidence_hash, expires_at) "
                 "VALUES (%s, %s, 'o1', 'RED', 'h', now() + interval '1 hour')", (p["id"], p["visit_id"]))
    cid = conn.execute("SELECT id FROM commands WHERE proposal_id = %s", (p["id"],)).fetchone()["id"]
    assert workflow.claim_command(conn, str(cid)) is None


def test_concurrent_double_claim_exactly_one_wins(conn):
    c = approved_command(conn)
    barrier = threading.Barrier(2)
    got: list = []

    def go():
        with db.connect() as cn:
            barrier.wait()
            got.append(workflow.claim_command(cn, str(c["id"])))

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(g is None for g in got) == [False, True]
    assert conn.execute("SELECT attempts FROM commands WHERE id = %s", (c["id"],)).fetchone()["attempts"] == 1


# ---------- E3-5: mark done, resume, sweep ----------

def test_mark_done_needs_a_claim_and_audits_once(conn):
    c = approved_command(conn)
    assert workflow.mark_done(conn, str(c["id"])) is None                 # not claimed yet
    workflow.claim_command(conn, str(c["id"]))
    done = workflow.mark_done(conn, str(c["id"]), run_id="run-1")
    assert done["done_at"] is not None
    assert workflow.mark_done(conn, str(c["id"])) is None                 # already done
    assert audit_kinds(conn, c["visit_id"]) == ["proposal_approved", "command_done"]
    assert conn.execute("SELECT run_id FROM audit_log WHERE kind = 'command_done' AND visit_id = %s",
                        (c["visit_id"],)).fetchone()["run_id"] == "run-1"


def test_resume_only_claimed_not_done_under_five_attempts(conn):
    c = approved_command(conn)
    cid = str(c["id"])
    assert workflow.resume_command(conn, cid) is None                     # never claimed
    workflow.claim_command(conn, cid)
    for expected in (2, 3, 4, 5):
        assert workflow.resume_command(conn, cid)["attempts"] == expected
    assert workflow.resume_command(conn, cid) is None                     # attempts reached 5
    d = approved_command(conn)
    workflow.claim_command(conn, str(d["id"]))
    workflow.mark_done(conn, str(d["id"]))
    assert workflow.resume_command(conn, str(d["id"])) is None


def test_sweep_lists_open_commands_only(conn):
    unclaimed, claimed, done = approved_command(conn), approved_command(conn), approved_command(conn)
    expired = workflow.approve_proposal(conn, str(make_proposal(conn)["id"]), "nurse-a",
                                        ttl=timedelta(seconds=-1))["command"]
    workflow.claim_command(conn, str(claimed["id"]))
    workflow.claim_command(conn, str(done["id"]))
    workflow.mark_done(conn, str(done["id"]))
    ids = {r["id"] for r in workflow.sweep_open_commands(conn)}
    assert unclaimed["id"] in ids and claimed["id"] in ids
    assert done["id"] not in ids and expired["id"] not in ids


def test_command_check_refuses_done_without_claim(conn):
    p = make_proposal(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO commands (proposal_id, visit_id, obs_id, colour, evidence_hash, expires_at, done_at) "
                     "VALUES (%s, %s, 'o1', 'RED', 'h', now(), now())", (p["id"], p["visit_id"]))


# ---------- E4-8: audit rows through the real table ----------

def test_pg_auditor_writes_one_row_and_checks_roles(conn):
    from afya_mcp import audit
    a = audit.PgAuditor()
    assert (a.role("nurse-a"), a.role("mgr-k"), a.role("nobody")) == ("nurse", "manager", None)
    v, run = new_id("v"), new_id("run")
    audit.call(a, "record_vitals", audit.ACT, {"visit_id": f"Encounter/{v}", "values": {"heart_rate": 80}},
               lambda: {"status": "saved"}, actor="nurse-a", run_id=run)
    with pytest.raises(audit.ActorRefused):
        audit.call(a, "record_vitals", audit.ACT, {"visit_id": v}, lambda: None, actor="nobody", run_id=run)
    rows = conn.execute("SELECT kind, actor, auth, visit_id, payload FROM audit_log WHERE run_id = %s ORDER BY id",
                        (run,)).fetchall()
    assert [(r["kind"], r["actor"], r["auth"], r["visit_id"]) for r in rows] == [
        ("record_vitals", "nurse-a", "demo_switcher", v), ("record_vitals_refused", "system", "service", v)]
    assert rows[0]["payload"]["output"] == {"status": "saved"} and "latency_ms" in rows[0]["payload"]


# ---------- E4-5: proposals for the queue ----------

def test_open_proposals_lists_pending_then_unreviewed_superseded_until_acknowledged(conn):
    p = make_proposal(conn, colour="RED")
    mine = lambda: [r for r in workflow.open_proposals(conn) if r["id"] == p["id"]]  # noqa: E731
    assert [(r["status"], r["to_colour"]) for r in mine()] == [("pending", "RED")]
    db.upsert_visit(conn, p["visit_id"], "p1", "o-newer")
    assert [r["status"] for r in mine()] == ["superseded"]
    assert workflow.acknowledge(conn, str(p["id"]), "nurse-a")
    assert mine() == []
