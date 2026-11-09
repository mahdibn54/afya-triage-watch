"""Made-up patient names and file numbers reach the screens only: never the model, the WSO2 projection or audit rows."""
from __future__ import annotations

import json

import pytest
from conftest import READING
from fake_model import decision, tool_call
from support import vitals

from afya_api.fhir_projection import PANEL_PATH, restore_response

NAME, FAMILY, FILE_NO = "Grace", "Achieng", "F-4242"
SECRETS = (NAME, FAMILY, FILE_NO)
PATIENT = {"resourceType": "Patient", "id": "p1", "birthDate": "1986-03-02", "gender": "other",
           "identifier": [{"system": "urn:afya:label", "value": "P-001"},
                          {"system": "urn:afya:file-number", "value": FILE_NO}],
           "name": [{"family": FAMILY, "given": [NAME], "text": f"{NAME} {FAMILY}"}],
           "telecom": [{"value": "000"}], "address": [{"text": "Nowhere"}]}


def test_wso2_projection_never_carries_a_patient(  # (a) the projected WSO2 result
):
    with pytest.raises(ValueError):
        restore_response("read", PATIENT)
    with pytest.raises(ValueError):
        restore_response("search", {"type": "searchset", "entry": [PATIENT]})


def test_wso2_projection_of_observation_and_encounter_strips_identity():
    obs = {"resourceType": "Observation", "id": "7", "encounter.reference": "Encounter/v1", PANEL_PATH: "85353-1",
           "subject.display": f"{NAME} {FAMILY}", "subject.identifier.value": FILE_NO, "name": PATIENT["name"],
           "identifier": PATIENT["identifier"], "telecom": PATIENT["telecom"], "address": PATIENT["address"]}
    assert not any(s in json.dumps(restore_response("read", obs)) for s in SECRETS)
    with pytest.raises(ValueError):   # an Encounter is not an Observation either
        restore_response("read", {"resourceType": "Encounter", "id": "v1", "subject": {"display": NAME}})


@pytest.fixture
def named(fhir):
    fhir.put(PATIENT)


def test_prompts_and_tool_results_hold_no_name_or_file_number(client, as_user, visit, backend, named):
    """(b) every message sent to map_signs and investigate, tool results included, via a get_queue_state call."""
    backend.script("investigate", tool_call("get_queue_state"), tool_call("fhir_search", count=3), decision())
    vitals(client, visit, **dict(READING, resp_rate=22, heart_rate=105, temperature=37.2))
    vitals(client, visit, **dict(READING, resp_rate=26, heart_rate=112, temperature=38.6))
    sent = json.dumps([x["messages"] for x in backend.seen])
    assert any(x["purpose"] == "investigate" for x in backend.seen)
    assert any(m["role"] == "tool" for x in backend.seen for m in x["messages"])
    assert not any(s in sent for s in SECRETS)


def test_audit_payloads_hold_no_name_or_file_number(client, as_user, visit, backend, gateway, conn, named):
    """(c) every audit row of the run (agent steps and the tool rows, get_queue_state included)."""
    backend.script("investigate", tool_call("get_queue_state"), tool_call("fhir_search", count=3), decision())
    vitals(client, visit, **dict(READING, resp_rate=22, heart_rate=105, temperature=37.2))
    out = vitals(client, visit, **dict(READING, resp_rate=26, heart_rate=112, temperature=38.6)).json()
    rows = conn.execute("SELECT payload FROM audit_log WHERE run_id = %s", (out["run_id"],)).fetchall()
    assert any(c[0] == "get_queue_state" for c in gateway.calls) and len(rows) >= 3
    text = json.dumps([r["payload"] for r in rows], default=str)
    assert not any(s in text for s in SECRETS)


def test_queue_endpoint_gives_the_screens_name_and_file_number(client, as_user, visit, named):
    as_user("nurse-a")
    row = next(p for p in client.get("/queue").json()["patients"] if p["visit_id"] == visit)
    assert row["patient_name"] == f"{NAME} {FAMILY}" and row["file_number"] == FILE_NO
    assert row["patient_label"] == "P-001"
