"""E6-1b: POST /vitals, GET /proposals, approve (decision), reject, acknowledge."""
from __future__ import annotations

import uuid

import pytest
from afya_mcp import services, workflow
from support import GOOD, error, new_proposal, vitals  # noqa: F401


def test_without_a_session_the_stub_answers_501(client):
    e = error(client.get("/proposals"), 501, "unavailable")
    assert "E6-2" in e["message"]


def test_vitals_saved_run_id_complaint_and_retry(client, as_user, visit, conn):
    key = uuid.uuid4().hex
    r = vitals(client, visit, key, complaint="Short of breath since morning.")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "saved" and body["observation_id"].startswith("Observation/")
    assert body["run_id"] == f"{visit}:{body['observation_id'].split('/')[1]}" and "problems" not in body
    again = vitals(client, visit, key, complaint="changed").json()
    assert again["observation_id"] == body["observation_id"]
    row = conn.execute("SELECT complaint FROM readings WHERE obs_id = %s", (body["observation_id"].split("/")[1],)
                       ).fetchone()
    assert row["complaint"] == "Short of breath since morning."
    audited = conn.execute("SELECT actor, payload FROM audit_log WHERE kind='record_vitals' AND visit_id=%s",
                           (visit,)).fetchone()
    assert audited["actor"] == "nurse-a" and "Short of breath" not in str(audited["payload"])


def test_vitals_impossible_value_is_remeasure_not_an_error(client, as_user, visit, fhir):
    r = client.post("/vitals", json={"visit_id": visit, "idempotency_key": "k-1", "heart_rate": 400})
    assert r.status_code == 200
    assert r.json() == {"status": "remeasure", "problems": [{"name": "heart_rate", "value": 400.0, "min": 20.0,
                                                             "max": 250.0}]}
    assert "Observation" not in fhir.data


@pytest.mark.parametrize("body", [
    {"idempotency_key": "k", "resp_rate": 20},                       # no visit
    {"visit_id": "x", "idempotency_key": "bad key!", "resp_rate": 20},
    {"visit_id": "x", "idempotency_key": "k", "pulse": 80},           # unknown input
    {"visit_id": "x", "idempotency_key": "k", "heart_rate": "fast"},
    {"visit_id": "x", "idempotency_key": "k", "mobility": "running"},
    {"visit_id": "x", "idempotency_key": "k", "resp_rate": 20, "complaint": "x" * 501},
])
def test_vitals_bad_input_is_422_in_the_error_shape(client, as_user, body):
    e = error(client.post("/vitals", json=body), 422, "invalid")
    assert e["problems"]


def test_vitals_without_any_value_is_422(client, as_user, visit):
    e = error(client.post("/vitals", json={"visit_id": visit, "idempotency_key": "k-2"}), 422, "invalid")
    assert "no values" in e["problems"]


def test_vitals_unknown_visit_404_and_manager_403_audited(client, as_user, visit, conn):
    error(client.post("/vitals", json={"visit_id": "nope", "idempotency_key": "k", "resp_rate": 20}), 404, "not_found")
    as_user("mgr-k")
    error(vitals(client, visit), 403, "forbidden")
    n = conn.execute("SELECT count(*) AS n FROM audit_log WHERE kind='record_vitals_refused' AND actor='mgr-k' "
                     "AND visit_id=%s", (visit,)).fetchone()["n"]
    assert n == 1


def test_proposals_list_matches_the_contract(client, as_user, visit, fhir, conn):
    pid, oid = new_proposal(conn, fhir, visit)
    r = client.get("/proposals")
    assert r.status_code == 200
    mine = next(p for p in r.json() if p["id"] == pid)
    assert mine["status"] == "pending" and mine["visit_id"] == visit and mine["patient_label"] == "P-001"
    assert mine["obs_id"] == f"Observation/{oid}" and mine["proposed_colour"] == "ORANGE"
    assert mine["current_colour"] == "YELLOW" and (mine["tews_before"], mine["tews_after"]) == (3, 6)
    assert mine["signs"][0]["quote_span"] == {"start": 0, "end": 15} and mine["reviewed"] is False
    assert mine["notices"] == [] and mine["reminder_due"] is False and mine["age_minutes"] == 0
    assert client.get("/proposals?status=all").status_code == 200
    error(client.get("/proposals?status=bogus"), 422, "invalid")


def test_proposal_complaint_falls_back_to_the_stored_reading_complaint(client, as_user, visit, fhir, conn):
    first = vitals(client, visit, complaint="Cough for two days").json()
    oid = first["observation_id"].split("/")[1]
    p = workflow.insert_proposal(conn, visit, "colour_rise", oid, "h-" + oid, {"to_colour": "ORANGE"})
    mine = next(x for x in client.get("/proposals").json() if x["id"] == str(p["id"]))
    assert mine["complaint"] == "Cough for two days"


def test_superseded_unreviewed_shows_not_reviewed_then_acknowledge(client, as_user, visit, fhir, conn):
    pid, _ = new_proposal(conn, fhir, visit)
    vitals(client, visit)   # newer reading supersedes
    mine = next(p for p in client.get("/proposals?status=superseded").json() if p["id"] == pid)
    assert mine["notices"] == [{"code": "not_reviewed", "notification_id": None, "at": None}]
    assert client.post(f"/proposals/{pid}/acknowledge").json() == {"proposal_id": pid, "reviewed": True}
    error(client.post(f"/proposals/{pid}/acknowledge"), 409, "conflict")
    assert pid not in [p["id"] for p in client.get("/proposals?status=superseded").json()]


def test_notification_acknowledge(client, as_user, visit, conn):
    vitals(client, visit)
    nid = services.notify_staff(conn, "vitals_due", visit_id=visit)["notification_id"]
    assert client.post(f"/notifications/{nid}/acknowledge").json() == {"notification_id": nid, "acknowledged": True}
    error(client.post(f"/notifications/{uuid.uuid4()}/acknowledge"), 404, "not_found")
    error(client.post("/notifications/nonsense/acknowledge"), 404, "not_found")


def test_clinician_reminder_is_translated_to_clinician_reminded(client, as_user, visit, fhir, conn):
    pid, _ = new_proposal(conn, fhir, visit)
    services.notify_staff(conn, "clinician_reminder", proposal_id=pid)
    mine = next(p for p in client.get("/proposals").json() if p["id"] == pid)
    assert [n["code"] for n in mine["notices"]] == ["clinician_reminded"] and mine["notices"][0]["notification_id"]


def test_approve_body_is_validated(client, as_user, visit, fhir, conn):
    pid, _ = new_proposal(conn, fhir, visit)
    error(client.post(f"/proposals/{pid}/approve", json={"colour": "PURPLE"}), 422, "invalid")
    error(client.post(f"/proposals/{pid}/approve", json={}), 422, "invalid")
    error(client.post(f"/proposals/{pid}/approve", json={"colour": "ORANGE", "signs_kept": ["NOT_SHOWN"]}), 422,
          "invalid")
    error(client.post("/proposals/not-a-uuid/approve", json={"colour": "ORANGE"}), 409, "conflict")


def test_manager_cannot_approve_or_reject_and_it_is_audited(client, as_user, visit, fhir, conn):
    pid, _ = new_proposal(conn, fhir, visit)
    as_user("mgr-k")
    error(client.post(f"/proposals/{pid}/approve", json={"colour": "ORANGE"}), 403, "forbidden")
    error(client.post(f"/proposals/{pid}/reject", json={"reason": "no"}), 403, "forbidden")
    kinds = [r["kind"] for r in conn.execute(
        "SELECT kind FROM audit_log WHERE payload->>'proposal_id' = %s ORDER BY id", (pid,))]
    assert kinds == ["approve_refused", "reject_refused"]
    assert "Flag" not in fhir.data


def test_reject(client, as_user, visit, fhir, conn):
    pid, _ = new_proposal(conn, fhir, visit)
    error(client.post(f"/proposals/{pid}/reject", json={"reason": ""}), 422, "invalid")
    error(client.post(f"/proposals/{pid}/reject", json={}), 422, "invalid")
    r = client.post(f"/proposals/{pid}/reject", json={"reason": "Re-measured at the desk, cuff error."})
    assert r.json() == {"proposal_id": pid, "status": "rejected"}
    error(client.post(f"/proposals/{pid}/reject", json={"reason": "again"}), 409, "conflict")
    error(client.post(f"/proposals/{pid}/approve", json={"colour": "ORANGE"}), 409, "conflict")
    assert "Flag" not in fhir.data
    assert pid not in [p["id"] for p in client.get("/proposals").json()]
