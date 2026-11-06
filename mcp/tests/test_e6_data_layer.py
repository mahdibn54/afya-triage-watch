"""Data layer for the E6 endpoints: complaint storage, proposal payload fields, override/reject, timeline, demo seed."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from afya_mcp import db, rules, services, workflow
from afya_mcp.workflow import Conflict, Forbidden, InvalidDecision
from fake_fhir import FakeFhir
from fake_store import FakeStore

REG = rules.load_registry()
LIMITS = rules.load_plausibility()
BASE = dict(resp_rate=14, heart_rate=80, systolic_bp=120, temperature=37.0, mobility="walking",
            consciousness="alert", trauma="no")


def fhir_with_visit():
    f = FakeFhir()
    f.put({"resourceType": "Patient", "id": "p1", "birthDate": "1990-03-02",
           "identifier": [{"system": "urn:afya:label", "value": "P-014"}]})
    f.put({"resourceType": "Encounter", "id": "v1", "status": "in-progress", "subject": {"reference": "Patient/p1"}})
    return f


# ---------- Q1 complaint ----------

def test_complaint_is_normalised_stored_in_store_and_not_in_fhir():
    f, store = fhir_with_visit(), FakeStore()
    out = services.record_vitals(f, LIMITS, REG, None, "v1", BASE, "k1", None, store, "  ＳＯＢ  since\x07 morning ")
    assert out["status"] == "saved"
    oid = out["observation_id"].split("/")[1]
    assert store.complaints[oid] == ("v1", "SOB  since  morning")
    assert "SOB" not in str(f.data["Observation"][oid])
    assert store.visits["v1"]["patient_label"] == "P-014"


def test_complaint_longer_than_500_after_nfkc_is_invalid():
    f, store = fhir_with_visit(), FakeStore()
    out = services.record_vitals(f, LIMITS, REG, "p1", "v1", BASE, "k1", None, store, "x" * 501)
    assert out["status"] == "invalid" and f.creates == 0 and not store.complaints
    assert services.record_vitals(f, LIMITS, REG, "p1", "v1", BASE, "k2", None, store, "x" * 500)["status"] == "saved"


def test_retry_keeps_first_complaint():
    f, store = fhir_with_visit(), FakeStore()
    services.record_vitals(f, LIMITS, REG, "p1", "v1", BASE, "k1", None, store, "first")
    services.record_vitals(f, LIMITS, REG, "p1", "v1", BASE, "k1", None, store, "second")
    assert [c for _, c in store.complaints.values()] == ["first"]



def test_reported_worsening_is_stored_with_the_reading_even_without_a_complaint():
    f, store = fhir_with_visit(), FakeStore()
    out = services.record_vitals(f, LIMITS, REG, "p1", "v1", BASE, "k1", None, store, None, True)
    assert out["status"] == "saved"
    assert store.worsening == {out["observation_id"].split("/")[1]} and not store.complaints


def test_reported_worsening_must_be_true_or_false():
    f, store = fhir_with_visit(), FakeStore()
    out = services.record_vitals(f, LIMITS, REG, "p1", "v1", BASE, "k1", None, store, None, "yes")
    assert out["status"] == "invalid" and f.creates == 0

# ---------- Q4/Q13 payload ----------

GOOD = {"to_colour": "ORANGE", "current_colour": "YELLOW", "tews_before": 3, "tews_after": 6,
        "reasons": ["colour rise"], "complaint": "short of breath", "rationale": "text", "rationale_source": "code",
        "agent_action": "propose", "missing_input": None, "signs_verdict": "found", "notices": [],
        "cited_obs_ids": ["1", "2"],
        "evidence": [{"input": "heart_rate", "unit": "/min", "band_changed": True,
                      "before": {"obs_id": "Observation/1", "value": 105, "points": 1},
                      "after": {"obs_id": "Observation/2", "value": 112, "points": 2}}],
        "signs": [{"code": "SOB_ACUTE", "gloss": "g", "colour": "ORANGE", "source": "complaint", "status": "current",
                   "quote": "short", "quote_span": {"start": 0, "end": 5}, "reason": None}]}


def test_payload_accepts_the_documented_fields():
    workflow._check_payload(GOOD)


@pytest.mark.parametrize("change", [
    {"surprise": 1}, {"agent_action": "diagnose"}, {"signs_verdict": "maybe"}, {"rationale_source": "x"},
    {"tews_after": "6"}, {"complaint": "x" * 501}, {"rationale": "x" * 301}, {"notices": [{"code": "nope"}]},
    {"evidence": [{"input": "hr"}]}, {"signs": [{"code": "A"}]}, {"reasons": "text"}, {"current_colour": "BLUE"},
])
def test_payload_refuses_bad_fields(change):
    with pytest.raises(ValueError):
        workflow._check_payload({**GOOD, **change})


def test_run_id_and_obs_ref():
    assert workflow.run_id_for("v014", "Observation/1057") == "v014:1057"
    assert workflow.run_id_for("Encounter/v014", "1057") == "v014:1057"
    assert workflow.obs_ref("1057") == workflow.obs_ref("Observation/1057") == "Observation/1057"
    with pytest.raises(ValueError):
        workflow.run_id_for("v 1", "2")


# ---------- timeline and demo ----------

def test_timeline_has_raw_values_points_and_unscored_spo2():
    f = fhir_with_visit()
    t0 = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)
    services.record_vitals(f, LIMITS, REG, "p1", "v1", {**BASE, "spo2": 97}, "a", t0)
    services.record_vitals(f, LIMITS, REG, "p1", "v1", {**BASE, "heart_rate": 112}, "b",
                           t0.replace(minute=30))
    tl = services.visit_timeline(f, REG, "v1")
    assert tl["chart_id"] == "sats_adult_2012" and len(tl["readings"]) == 2
    first, second = tl["readings"]
    assert first["at"] < second["at"]
    assert first["values"]["spo2"] == {"value": 97, "unit": "%", "points": None}
    assert second["values"]["heart_rate"] == {"value": 112, "unit": "/min", "points": 2} and second["tews"] == 2
    assert first["values"]["mobility"]["unit"] is None
    assert services.visit_timeline(f, REG, "nope")["status"] == "not_found"


def test_seed_demo_visit_reload_finishes_the_previous_visit():
    f = FakeFhir()
    a = services.seed_demo_visit(f, "P-014", "1986-01-01", 52, "YELLOW")
    b = services.seed_demo_visit(f, "P-014", "1986-01-01", 52, "YELLOW")
    assert a["patient_id"] == b["patient_id"] and a["visit_id"] != b["visit_id"]
    assert f.data["Encounter"][a["visit_id"]]["status"] == "finished"
    assert services.demo_visit(f, "P-014")["visit_id"] == b["visit_id"]
    assert services.demo_visit(f, "P-014")["readings"] == 0
    assert services.seed_demo_visit(f, "bad label", "1986-01-01", 1, "YELLOW")["status"] == "invalid"
    assert services.demo_visit(f, "P-999")["status"] == "not_found"


# ---------- Postgres: approve with override, reject ----------

def _reachable():
    url = os.environ.get("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except psycopg.Error:
        return False


pg = pytest.mark.skipif(not _reachable(), reason="DATABASE_URL not set or Postgres not reachable")


def _proposal(conn, payload=None):
    v = f"t-{uuid.uuid4().hex[:10]}"
    db.upsert_visit(conn, v, "p1", "o1", "P-1")
    p = workflow.insert_proposal(conn, v, "colour_rise", "o1", workflow.evidence_hash(["o1"], [], "r"),
                                 payload or GOOD)
    return str(p["id"]), v


def _kinds(conn, v):
    return [r["kind"] for r in conn.execute("SELECT kind FROM audit_log WHERE visit_id = %s ORDER BY id", (v,))]


@pg
def test_approve_default_colour_records_signs_kept():
    with db.connect() as c:
        pid, v = _proposal(c)
        out = workflow.approve_proposal(c, pid, "nurse-a", signs_kept=["SOB_ACUTE"])
        assert out["command"]["colour"] == "ORANGE"
        row = c.execute("SELECT payload FROM audit_log WHERE kind='proposal_approved' AND visit_id=%s", (v,)).fetchone()
        assert row["payload"]["signs_kept"] == ["SOB_ACUTE"] and "override_reason" not in row["payload"]


@pg
def test_override_to_a_lower_colour_needs_a_reason_and_sets_the_command_colour():
    with db.connect() as c:
        pid, v = _proposal(c)
        for reason in (None, "   "):
            with pytest.raises(InvalidDecision):
                workflow.approve_proposal(c, pid, "nurse-a", colour="YELLOW", override_reason=reason)
        # the failed attempts rolled back: still pending, refusals audited
        assert c.execute("SELECT status FROM proposals WHERE id=%s", (pid,)).fetchone()["status"] == "pending"
        out = workflow.approve_proposal(c, pid, "clin-m", colour="YELLOW", override_reason="cuff error")
        assert out["command"]["colour"] == "YELLOW"
        row = c.execute("SELECT payload FROM audit_log WHERE kind='proposal_approved' AND visit_id=%s", (v,)).fetchone()
        assert row["payload"]["override_reason"] == "cuff error" and row["payload"]["proposed_colour"] == "ORANGE"
        assert c.execute("SELECT count(*) AS n FROM audit_log WHERE kind='approve_refused' AND payload->>'proposal_id'"
                         "=%s AND payload->>'reason'='invalid'", (pid,)).fetchone()["n"] == 2


@pg
def test_approve_refuses_unknown_colour_and_unknown_signs():
    with db.connect() as c:
        pid, _ = _proposal(c)
        with pytest.raises(InvalidDecision):
            workflow.approve_proposal(c, pid, "nurse-a", colour="BLUE", override_reason="x")
        with pytest.raises(InvalidDecision):
            workflow.approve_proposal(c, pid, "nurse-a", signs_kept=["OTHER"])


@pg
def test_reject_has_the_same_role_check_and_single_use():
    with db.connect() as c:
        pid, v = _proposal(c)
        with pytest.raises(Forbidden):
            workflow.reject_proposal(c, pid, "mgr-k", "no")
        with pytest.raises(InvalidDecision):
            workflow.reject_proposal(c, pid, "nurse-a", "  ")
        assert workflow.reject_proposal(c, pid, "nurse-a", "cuff error")["proposal"]["status"] == "rejected"
        with pytest.raises(Conflict):
            workflow.reject_proposal(c, pid, "nurse-a", "again")
        with pytest.raises(Conflict):
            workflow.approve_proposal(c, pid, "nurse-a")
        assert c.execute("SELECT count(*) AS n FROM commands WHERE proposal_id=%s", (pid,)).fetchone()["n"] == 0
        kinds = [r["kind"] for r in c.execute(
            "SELECT kind FROM audit_log WHERE payload->>'proposal_id' = %s ORDER BY id", (pid,))]
        assert kinds == ["reject_refused", "proposal_rejected", "reject_refused", "approve_refused"]


@pg
def test_guard_blocks_manager_reject_by_direct_update():
    with db.connect() as c:
        pid, _ = _proposal(c)
        with pytest.raises(psycopg.Error):
            c.execute("UPDATE proposals SET status='rejected', decided_by='mgr-k', decided_at=now() WHERE id=%s",
                      (pid,))


@pg
def test_complaint_row_is_written_once_and_notifications_can_be_acknowledged():
    with db.connect() as c:
        _, v = _proposal(c)
        store = db.PgVisitStore()
        store.save_complaint(v, "o-" + v, "first")
        store.save_complaint(v, "o-" + v, "second")
        row = c.execute("SELECT complaint FROM readings WHERE obs_id=%s", ("o-" + v,)).fetchone()
        assert row["complaint"] == "first"
        n = services.notify_staff(c, "vitals_due", visit_id=v)["notification_id"]
        assert any(str(x["id"]) == n for x in workflow.open_notifications(c))
        assert workflow.acknowledge_notification(c, n, "nurse-a") is True
        assert not any(str(x["id"]) == n for x in workflow.open_notifications(c))
        assert workflow.acknowledge_notification(c, str(uuid.uuid4()), "nurse-a") is False
