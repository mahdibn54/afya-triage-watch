"""Integration tests for the Postgres layer (db.py, workflow.py) against the running database, as afya_app.

Set TEST_DATABASE_URL to an afya_app URL of the separate test database `afya_test` (evals/stack_env.sh prints it; see
mcp/tests/dbselect.py: never the stack's own `afya`). Skipped when it is not set or not reachable. afya_app cannot
DELETE, so every test uses fresh ids tagged `synthetic-test-...` and leaves its rows behind (test database only).
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


TAG = "synthetic-test"   # every row these tests leave in the dev database has an id starting with this


def new_id(prefix="v"):
    return f"{TAG}-{prefix}-{uuid.uuid4().hex[:12]}"


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
    with pytest.raises(psycopg.Error):      # expiry beyond the timestamp range: the command INSERT fails
        workflow.approve_proposal(conn, str(p["id"]), "nurse-a", ttl=timedelta(days=10**8))
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


def test_database_refuses_a_command_for_a_proposal_that_is_not_approved(conn):
    p = make_proposal(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO commands (proposal_id, visit_id, obs_id, colour, evidence_hash, expires_at) "
                     "VALUES (%s, %s, 'o1', 'RED', %s, now() + interval '1 hour')",
                     (p["id"], p["visit_id"], p["evidence_hash"]))


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
    assert audit_kinds(conn, c["visit_id"]) == ["proposal_approved", "command_claimed", "command_done"]
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
    c = approved_command(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE commands SET done_at = now() WHERE id = %s", (c["id"],))


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


# ---------- E12-2: abandoned commands, grants, invariants ----------

def test_sweep_abandons_expired_and_stale_commands_with_audit_and_one_notice(conn):
    expired = workflow.approve_proposal(conn, str(make_proposal(conn)["id"]), "nurse-a",
                                        ttl=timedelta(seconds=-1))["command"]
    stale = approved_command(conn)
    db.upsert_visit(conn, stale["visit_id"], "p1", "o-newer")           # newer vitals after the approval
    live = approved_command(conn)
    ids = {r["id"] for r in workflow.sweep_open_commands(conn)}
    assert live["id"] in ids and expired["id"] not in ids and stale["id"] not in ids
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM commands WHERE id = ANY(%s)",
                                             ([expired["id"], stale["id"], live["id"]],))}
    assert rows[expired["id"]]["abandon_reason"] == "expired" and rows[stale["id"]]["abandon_reason"] == "stale"
    assert rows[live["id"]]["abandoned_at"] is None
    for c, why in ((expired, "expired"), (stale, "stale")):
        a = conn.execute("SELECT actor, auth, payload FROM audit_log WHERE kind = 'command_abandoned' "
                         "AND visit_id = %s", (c["visit_id"],)).fetchall()
        assert len(a) == 1 and a[0]["actor"] == "system" and a[0]["auth"] == "service"
        assert a[0]["payload"]["reason"] == why
    notes = conn.execute("SELECT kind, target_role FROM notifications WHERE visit_id = %s", (expired["visit_id"],))
    assert [(n["kind"], n["target_role"]) for n in notes] == [("command_abandoned", "nurse")]
    assert conn.execute("SELECT count(*) AS n FROM notifications WHERE visit_id = %s",
                        (stale["visit_id"],)).fetchone()["n"] == 0        # stale: audited, no notice
    assert workflow.claim_command(conn, str(expired["id"])) is None
    assert workflow.mark_done(conn, str(expired["id"])) is None
    again = workflow.abandon_unrunnable_commands(conn)                   # idempotent
    assert expired["id"] not in {r["id"] for r in again}


def test_command_that_used_all_attempts_is_abandoned(conn):
    c = approved_command(conn)
    cid = str(c["id"])
    workflow.claim_command(conn, cid)
    for _ in range(4):
        workflow.resume_command(conn, cid)
    assert cid not in {str(r["id"]) for r in workflow.sweep_open_commands(conn)}
    row = conn.execute("SELECT abandon_reason FROM commands WHERE id = %s", (cid,)).fetchone()
    assert row["abandon_reason"] == "attempts"
    assert workflow.resume_command(conn, cid) is None and workflow.mark_done(conn, cid) is None


def test_abandoned_and_done_are_exclusive(conn):
    c = approved_command(conn)
    workflow.claim_command(conn, str(c["id"]))
    workflow.mark_done(conn, str(c["id"]))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE commands SET abandoned_at = now(), abandon_reason = 'expired' WHERE id = %s", (c["id"],))


def test_app_role_cannot_rewrite_decided_content(conn):
    c = approved_command(conn)
    for sql in ("UPDATE proposals SET payload = '{\"to_colour\": \"GREEN\"}' WHERE id = %s",
                "UPDATE proposals SET obs_id = 'x' WHERE id = %s",
                "UPDATE proposals SET evidence_hash = 'x' WHERE id = %s",
                "UPDATE proposals SET visit_id = 'x' WHERE id = %s"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql, (c["proposal_id"],))
    for sql in ("UPDATE commands SET colour = 'GREEN' WHERE id = %s",
                "UPDATE commands SET expires_at = now() WHERE id = %s",
                "UPDATE commands SET evidence_hash = 'x' WHERE id = %s",
                "UPDATE commands SET obs_id = 'x' WHERE id = %s"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql, (c["id"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE visits SET patient_id = 'other' WHERE id = %s", (c["visit_id"],))


def test_proposal_cannot_be_inserted_already_decided_and_approval_needs_a_command(conn):
    v = new_id("v")
    db.upsert_visit(conn, v, "p1", "o1")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO proposals (visit_id, trigger, evidence_hash, obs_id, payload, status, decided_by) "
                     "VALUES (%s, 'colour_rise', 'h1', 'o1', '{\"to_colour\": \"RED\"}', 'approved', 'nurse-a')", (v,))
    p = make_proposal(conn)
    with pytest.raises(psycopg.errors.CheckViolation):      # approved without a command: refused at commit
        conn.execute("UPDATE proposals SET status = 'approved', decided_by = 'nurse-a', decided_at = now() "
                     "WHERE id = %s", (p["id"],))
    assert conn.execute("SELECT status FROM proposals WHERE id = %s", (p["id"],)).fetchone()["status"] == "pending"


def test_insert_proposal_for_an_older_reading_is_born_superseded(conn):
    v = new_id("v")
    db.upsert_visit(conn, v, "p1", "o2")
    p = workflow.insert_proposal(conn, v, "colour_rise", "o1", workflow.evidence_hash(["o1"], [], "r1"),
                                 {"to_colour": "RED"})
    assert p["status"] == "superseded" and p["reviewed"] is False
    assert [r["id"] for r in workflow.open_proposals(conn) if r["visit_id"] == v] == [p["id"]]


def test_refusals_carry_the_visit_and_service_actors_are_not_demo_switcher(conn):
    p = make_proposal(conn)
    with pytest.raises(Forbidden):
        workflow.approve_proposal(conn, str(p["id"]), "mgr-k")
    workflow.approve_proposal(conn, str(p["id"]), "nurse-a")
    with pytest.raises(Conflict):
        workflow.approve_proposal(conn, str(p["id"]), "clin-m")
    refusals = conn.execute("SELECT visit_id FROM audit_log WHERE kind = 'approve_refused' "
                            "AND payload->>'proposal_id' = %s", (str(p["id"]),)).fetchall()
    assert len(refusals) == 2 and all(r["visit_id"] == p["visit_id"] for r in refusals)
    workflow.claim_command(conn, str(conn.execute("SELECT id FROM commands WHERE proposal_id = %s",
                                                  (p["id"],)).fetchone()["id"]), "agent")
    auth = {r["kind"]: r["auth"] for r in conn.execute("SELECT kind, auth FROM audit_log WHERE visit_id = %s",
                                                       (p["visit_id"],))}
    assert auth["command_claimed"] == "service" and auth["proposal_approved"] == "demo_switcher"


def test_decision_closes_the_clinician_reminders(conn):
    from afya_mcp import services
    approved, rejected, other = make_proposal(conn), make_proposal(conn), make_proposal(conn)
    for p in (approved, rejected, other):
        services.notify_staff(conn, "clinician_reminder", str(p["id"]))
    open_for = lambda p: conn.execute(  # noqa: E731
        "SELECT count(*) AS n FROM notifications WHERE proposal_id = %s AND acknowledged_at IS NULL",
        (p["id"],)).fetchone()["n"]
    workflow.approve_proposal(conn, str(approved["id"]), "nurse-a")
    workflow.reject_proposal(conn, str(rejected["id"]), "clin-m", "not needed")
    db.upsert_visit(conn, other["visit_id"], "p1", "o-newer")           # supersedes `other`
    assert (open_for(approved), open_for(rejected), open_for(other)) == (0, 0, 0)


def test_list_proposals_filters_by_visit_and_limits_newest_first_for_all(conn):
    v = new_id("v")
    db.upsert_visit(conn, v, "p1", "o1")
    ids = []
    for i in range(3):
        db.upsert_visit(conn, v, "p1", f"o{i + 1}")
        ids.append(workflow.insert_proposal(conn, v, "colour_rise", f"o{i + 1}",
                                            workflow.evidence_hash([f"o{i + 1}"], [], "r1"),
                                            {"to_colour": "RED"})["id"])
    mine = workflow.list_proposals(conn, "all", v)
    assert [r["id"] for r in mine] == ids[::-1]
    assert [r["id"] for r in workflow.list_proposals(conn, "all", v, 2)] == ids[::-1][:2]
    assert [r["id"] for r in workflow.list_proposals(conn, "pending", v)] == ids[2:]
    assert workflow.list_proposals(conn, "all", new_id("none")) == []
    with pytest.raises(ValueError):
        workflow.list_proposals(conn, "all", v, 0)


def test_latest_obs_only_moves_forward_in_time(conn):
    from datetime import datetime, timezone
    v = new_id("v")
    t = lambda m: datetime(2030, 1, 1, 0, m, tzinfo=timezone.utc)  # noqa: E731
    db.upsert_visit(conn, v, "p1", "o2", None, t(2))
    db.upsert_visit(conn, v, "p1", "o1", None, t(1))            # a slower call with an older reading
    assert conn.execute("SELECT latest_obs_id FROM visits WHERE id = %s", (v,)).fetchone()["latest_obs_id"] == "o2"
    db.upsert_visit(conn, v, "p1", "o3", None, t(3))
    assert conn.execute("SELECT latest_obs_id FROM visits WHERE id = %s", (v,)).fetchone()["latest_obs_id"] == "o3"


def test_record_reading_saves_visit_and_complaint_in_one_transaction(conn):
    v, o, o2 = new_id("v"), new_id("obs"), new_id("obs")
    db.PgVisitStore().record_reading(v, "p1", o, "SYNTH-1", reading_obs_id=o, complaint="cough",
                                     reported_worsening=True)
    row = conn.execute("SELECT complaint, reported_worsening FROM readings WHERE obs_id = %s AND visit_id = %s",
                       (o, v)).fetchone()
    assert (row["complaint"], row["reported_worsening"]) == ("cough", True)
    v2 = new_id("v")
    with pytest.raises(psycopg.Error):     # the complaint insert fails (over 500 characters): the visit is not kept
        db.PgVisitStore().record_reading(v2, "p1", o2, reading_obs_id=o2, complaint="x" * 501)
    assert conn.execute("SELECT count(*) AS n FROM visits WHERE id = %s", (v2,)).fetchone()["n"] == 0


def test_schema_version_is_recorded(conn):
    assert conn.execute("SELECT max(version) AS v FROM schema_version").fetchone()["v"] >= 2
