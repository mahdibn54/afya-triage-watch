"""E5-4: the investigate loop (scripted model): read-only tools, limits, forged write tool refused, trimming."""
from __future__ import annotations

import json

from conftest import READING
from fake_model import decision, signs_reply, tool_call
from support import vitals

from afya_api.investigate import trim_observation
from afya_api.model import Reply

STABLE_YELLOW = dict(READING, resp_rate=22, heart_rate=105, temperature=37.2)
OFFERED = {"fhir_search", "fhir_read", "get_queue_state", "check_deterioration", "compute_tews", "submit_decision"}


def two_readings(client, visit, **extra):
    vitals(client, visit, **STABLE_YELLOW)                 # YELLOW, same as confirmed: logged only
    return vitals(client, visit, **extra).json()          # ORANGE: colour rise -> investigate


def facts(messages):
    return json.loads(messages[1]["content"])


def card(client, visit):
    return [p for p in client.get("/proposals").json() if p["visit_id"] == visit][-1]


def trace(client, run_id):
    return client.get(f"/runs/{run_id}/trace").json()


def test_loop_with_a_borrowed_search_then_a_decision_rejecting_unseen_ids(client, as_user, visit, backend, gateway):
    def decide(messages, tools):
        prev = facts(messages)["previous_reading"]["id"]
        return decision("propose_and_remeasure", rationale=f"Heart rate rose ({prev}).",
                        cited_ids=[prev, "Observation/999999999"])
    backend.script("investigate", tool_call("fhir_search", count=3), decide)
    out = two_readings(client, visit)
    p = card(client, visit)
    assert p["agent_action"] == "propose_and_remeasure"
    steps = trace(client, out["run_id"])
    search = next(s for s in steps if s["name"] == "search")
    assert search["server"] == "borrowed" and search["result_summary"] == "2 readings"
    sub = next(s for s in steps if s["name"] == "submit_decision")
    assert "1 cited id(s) rejected" in sub["result_summary"]
    inv = [s for s in steps if s["name"] == "investigate"]
    assert len(inv) == 2 and inv[0]["kind"] == "model" and inv[0]["tokens_in"] == 800
    sent = [x for x in backend.seen if x["purpose"] == "investigate"]
    assert {t["function"]["name"] for t in sent[0]["tools"]} == OFFERED         # bound list = ToolNode list
    assert sent[0]["options"]["temperature"] == 0.2
    tool_msg = next(m for m in sent[1]["messages"] if m["role"] == "tool")
    rows = json.loads(tool_msg["content"])["readings"]
    assert set(rows[0]) == {"id", "time", "values"} and all(set(v) == {"code", "value", "unit"}
                                                              for v in rows[0]["values"])


def test_forged_write_tool_call_is_refused(client, as_user, visit, backend, gateway, fhir):
    backend.script("investigate", tool_call("raise_recheck_flag", command_id="00000000-0000-0000-0000-000000000000",
                                            actor="nurse-a"), decision())
    out = two_readings(client, visit)
    assert not [c for c in gateway.calls if c[0] == "raise_recheck_flag"]
    assert not fhir.data.get("Flag")
    refused = next(s for s in trace(client, out["run_id"]) if s["name"] == "raise_recheck_flag")
    assert refused["result_summary"].startswith("refused")
    second = [x for x in backend.seen if x["purpose"] == "investigate"][1]["messages"]
    tool_msg = next(m for m in second if m["role"] == "tool")
    assert "not a valid tool" in tool_msg["content"]
    assert card(client, visit)["status"] == "pending"     # the code-built proposal still stands


def test_only_sign_codes_reach_investigate_never_the_complaint(client, as_user, visit, backend):
    backend.script("map_signs", signs_reply("found", ("SOB_ACUTE", "Short of breath", "current")))
    backend.script("investigate", decision())
    two_readings(client, visit, complaint="Short of breath since morning, call me Amina")
    sent = [x for x in backend.seen if x["purpose"] == "investigate"][0]
    text = json.dumps(sent["messages"])
    assert "SOB_ACUTE" in text and "Short of breath" not in text and "Amina" not in text
    assert facts(sent["messages"])["validated_sign_codes"] == ["SOB_ACUTE"]


def test_at_most_four_tool_calls(client, as_user, visit, backend, gateway):
    six = Reply("", tool_calls=[{"name": "fhir_search", "args": {"count": 1}}] * 6, tokens_in=1, tokens_out=1)
    backend.script("investigate", six, tool_call("get_queue_state"), decision())
    out = two_readings(client, visit)
    assert len([c for c in gateway.calls if c[0] == "wso2.search"]) == 4
    assert not [c for c in gateway.calls if c[0] == "get_queue_state"]   # the budget was used up
    first = next(s for s in trace(client, out["run_id"]) if s["name"] == "investigate")
    assert "2 call(s) over the limit of 4 dropped" in first["result_summary"]


def test_compute_tews_only_on_earlier_readings(client, as_user, visit, backend):
    def tews_current(messages, tools):
        return tool_call("compute_tews", observation_id=facts(messages)["reading"]["id"])
    backend.script("investigate", tews_current, decision())
    two_readings(client, visit)
    second = [x for x in backend.seen if x["purpose"] == "investigate"][1]["messages"]
    assert "only earlier readings" in next(m for m in second if m["role"] == "tool")["content"]


def test_model_down_in_investigate_keeps_the_code_proposal(client, as_user, visit, backend):
    two_readings(client, visit)                       # nothing scripted: the model is down
    p = card(client, visit)
    assert (p["agent_action"], p["rationale_source"], p["proposed_colour"]) == ("propose", "code", "ORANGE")


def test_trim_observation_keeps_loinc_quantities_only():
    obs = {"resourceType": "Observation", "id": "7", "effectiveDateTime": "t",
           "identifier": [{"system": "urn:afya:req", "value": "k"}], "subject": {"reference": "Patient/p1"},
           "note": [{"text": "free text"}], "code": {"coding": [{"system": "http://loinc.org", "code": "85353-1"}]},
           "component": [
               {"code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
                "valueQuantity": {"value": 112, "unit": "/min", "code": "/min"}},
               {"code": {"coding": [{"system": "urn:afya:codes", "code": "avpu"}]},
                "valueCodeableConcept": {"coding": [{"code": "alert"}], "text": "free"}},
               {"code": {"coding": [{"system": "http://loinc.org", "code": "99999-9"}]},
                "valueQuantity": {"value": 1}}]}
    assert trim_observation(obs) == {"id": "Observation/7", "time": "t",
                                     "values": [{"code": "8867-4", "value": 112, "unit": "/min"}]}
    assert trim_observation({"resourceType": "Patient", "id": "p1"}) is None
