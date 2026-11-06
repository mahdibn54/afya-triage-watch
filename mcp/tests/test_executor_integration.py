"""E4-6 raise_recheck_flag against the real Postgres (as afya_app) and an in-memory FHIR.

Same rules as test_postgres_integration.py: skipped without DATABASE_URL, fresh ids, rows are left behind.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from afya_mcp import db, services, workflow
from afya_mcp.fhir import COLOUR_SYSTEM, FhirUnavailable, confirmed_colour
from fake_fhir import FakeFhir

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


def setup_visit(conn, fhir, colour_now="YELLOW"):
    """Patient + Encounter in FHIR, visit row whose latest reading is o-<visit>."""
    v = new_id("v")
    fhir.put({"resourceType": "Patient", "id": f"p-{v}", "birthDate": "1990-01-01"})
    enc = {"resourceType": "Encounter", "id": v, "status": "in-progress", "subject": {"reference": f"Patient/p-{v}"}}
    if colour_now:
        enc["priority"] = {"coding": [{"system": COLOUR_SYSTEM, "code": colour_now}], "text": "kept"}
    fhir.put(enc)
    db.upsert_visit(conn, v, f"p-{v}", f"o-{v}")
    return v


def approved(conn, fhir, colour="ORANGE", cited=("o-prev",), approver="nurse-a"):
    v = setup_visit(conn, fhir)
    p = workflow.insert_proposal(conn, v, "colour_rise", f"o-{v}",
                                 workflow.evidence_hash([f"o-{v}", *cited], [], "sats_adult_2012"),
                                 {"to_colour": colour, "cited_obs_ids": list(cited)})
    return workflow.approve_proposal(conn, str(p["id"]), approver)["command"]


def flags(fhir):
    return list(fhir.data.get("Flag", {}).values())


def kinds(conn, visit):
    return [r["kind"] for r in conn.execute("SELECT kind FROM audit_log WHERE visit_id = %s ORDER BY id", (visit,))]


# ---------- E4-6 ----------

def test_writes_flag_and_priority_then_marks_done_with_audit(conn):
    fhir = FakeFhir()
    c = approved(conn, fhir)
    out = services.raise_recheck_flag(fhir, conn, str(c["id"]), "nurse-a", "run-x")
    assert out["status"] == "done" and out["colour"] == "ORANGE" and out["priority_changed"] is True
    [flag] = flags(fhir)
    assert flag["identifier"] == [{"system": "urn:afya:command", "value": str(c["id"])}]
    assert flag["code"]["coding"][0]["code"] == "second-look"
    assert flag["encounter"]["reference"] == f"Encounter/{c['visit_id']}"
    assert flag["subject"]["reference"] == f"Patient/p-{c['visit_id']}"
    cited = [e["valueReference"]["reference"] for e in flag["extension"] if e["url"] == "urn:afya:evidence"]
    assert cited == [f"Observation/{c['obs_id']}", "Observation/o-prev"]
    enc = fhir.data["Encounter"][c["visit_id"]]
    assert confirmed_colour(enc) == "ORANGE" and enc["priority"]["text"] == "kept"
    row = conn.execute("SELECT done_at, attempts FROM commands WHERE id = %s", (c["id"],)).fetchone()
    assert row["done_at"] is not None and row["attempts"] == 1
    assert kinds(conn, c["visit_id"])[-1] == "command_done"


def test_retry_after_failure_between_fhir_write_and_mark_done_converges_to_one_flag(conn, monkeypatch):
    fhir = FakeFhir()
    c = approved(conn, fhir)
    real = workflow.mark_done

    def crash(*a, **k):
        raise psycopg.OperationalError("simulated crash after the FHIR write")
    monkeypatch.setattr(workflow, "mark_done", crash)
    with pytest.raises(psycopg.OperationalError):
        services.raise_recheck_flag(fhir, conn, str(c["id"]), "nurse-a")
    assert len(flags(fhir)) == 1
    assert conn.execute("SELECT done_at FROM commands WHERE id = %s", (c["id"],)).fetchone()["done_at"] is None

    monkeypatch.setattr(workflow, "mark_done", real)
    out = services.raise_recheck_flag(fhir, conn, str(c["id"]), "system")   # startup sweep / retry
    assert out["status"] == "done" and out["attempts"] == 2
    assert len(flags(fhir)) == 1 and fhir.creates == 1
    assert out["flag_id"] == f"Flag/{flags(fhir)[0]['id']}"
    again = services.raise_recheck_flag(fhir, conn, str(c["id"]), "nurse-a")
    assert again["status"] == "already_done" and again["flag_id"] == out["flag_id"]
    assert len(flags(fhir)) == 1 and kinds(conn, c["visit_id"]).count("command_done") == 1


def test_fhir_down_leaves_the_command_claimed_and_a_retry_finishes_it(conn):
    fhir = FakeFhir()
    c = approved(conn, fhir)
    fhir.down = True
    with pytest.raises(FhirUnavailable):
        services.raise_recheck_flag(fhir, conn, str(c["id"]), "nurse-a")
    fhir.down = False
    assert services.raise_recheck_flag(fhir, conn, str(c["id"]), "nurse-a")["status"] == "done"
    assert len(flags(fhir)) == 1


def test_priority_already_set_is_not_rewritten(conn):
    fhir = FakeFhir()
    c = approved(conn, fhir, colour="YELLOW")
    assert services.raise_recheck_flag(fhir, conn, str(c["id"]), "nurse-a")["priority_changed"] is False


def test_only_the_approving_user_or_agent_system_may_execute(conn):
    fhir = FakeFhir()
    c = approved(conn, fhir)
    out = services.raise_recheck_flag(fhir, conn, str(c["id"]), "clin-m")
    assert out["status"] == "refused" and flags(fhir) == []
    assert services.raise_recheck_flag(fhir, conn, str(c["id"]), "agent")["status"] == "done"


def test_newer_vitals_after_approval_refuse_the_claim(conn):
    fhir = FakeFhir()
    c = approved(conn, fhir)
    db.upsert_visit(conn, c["visit_id"], f"p-{c['visit_id']}", "o-newer")
    out = services.raise_recheck_flag(fhir, conn, str(c["id"]), "nurse-a")
    assert out["status"] == "refused" and "newer vitals" in out["reason"] and flags(fhir) == []


def test_unknown_invalid_and_locked_commands(conn):
    fhir = FakeFhir()
    assert services.raise_recheck_flag(fhir, conn, "not-a-uuid", "nurse-a")["status"] == "invalid"
    assert services.raise_recheck_flag(fhir, conn, str(uuid.uuid4()), "nurse-a")["status"] == "not_found"
    c = approved(conn, fhir)
    with db.connect() as other:   # another executor holds the command
        other.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (str(c["id"]),))
        assert services.raise_recheck_flag(fhir, conn, str(c["id"]), "nurse-a")["status"] == "in_progress"
    assert services.raise_recheck_flag(fhir, conn, str(c["id"]), "nurse-a")["status"] == "done"


def test_executor_registry_is_keyed_by_action_type():
    assert services.EXECUTORS == {"recheck_flag": services.write_recheck_flag}


# ---------- proposal payload (open point from the DB agent) ----------

@pytest.mark.parametrize("payload", [{}, {"to_colour": "orange"}, {"to_colour": "BLUE"}, [],
                                     {"to_colour": "RED", "cited_obs_ids": "o1"},
                                     {"to_colour": "RED", "cited_obs_ids": [1]}])
def test_insert_proposal_requires_a_valid_to_colour(conn, payload):
    v = new_id("v")
    db.upsert_visit(conn, v, "p1", "o1")
    with pytest.raises(ValueError):
        workflow.insert_proposal(conn, v, "colour_rise", "o1", "h", payload)
    assert conn.execute("SELECT count(*) AS n FROM proposals WHERE visit_id = %s", (v,)).fetchone()["n"] == 0

