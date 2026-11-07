"""E5-4: the investigate loop (scripted model): read-only tools, limits, forged write tool refused, trimming."""
from __future__ import annotations

import json

from conftest import READING
from fake_model import decision, signs_reply, tool_call
from support import vitals

from afya_api.decision import VOCABULARY, rationale_facts, rationale_text
from afya_api.investigate import (
    PROMPT,
    RATIONALE_EXAMPLE,
    RATIONALE_EXAMPLE_SIGN,
    RATIONALE_WORDS,
    trim_observation,
)
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
    assert set(rows[0]) == {"id", "time", "values"} and all(set(v) == {"input", "code", "value", "unit"}
                                                              for v in rows[0]["values"])
    assert {"input": "heart rate", "code": "8867-4", "value": 105, "unit": "/min"} in rows[-1]["values"]


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


# ---------- E12-5: the model fetches the trend itself; the rationale guidance matches the filter ----------

def test_facts_hold_the_trigger_and_current_reading_not_the_earlier_values(client, as_user, visit, backend):
    backend.script("investigate", decision())
    two_readings(client, visit)
    f = facts([x for x in backend.seen if x["purpose"] == "investigate"][0]["messages"])
    assert set(f) == {"visit_id", "trigger", "reading", "confirmed_colour", "previous_reading", "validated_sign_codes"}
    assert set(f["previous_reading"]) == {"id"} and f["trigger"]["kind"] == "colour_rise"
    assert "changes" not in json.dumps(f) and "points" not in json.dumps(f)


def test_model_chosen_own_and_borrowed_reads_then_a_cited_decision(client, as_user, visit, backend, gateway):
    """One turn with a borrowed search and two own reads, then a decision citing what the search returned; the
    rationale uses the guidance's words and passes the filter. Each read is a trace row of its server."""
    def decide(messages, tools):
        tool_rows = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        readings = next(r["readings"] for r in tool_rows if "readings" in r)
        changes = next(r["changes"] for r in tool_rows if "changes" in r)
        assert {c["input"] for c in changes} >= {"heart rate"}      # labelled, never heart_rate
        assert all(set(c) == {"input", "score_band", "before", "after"} for c in changes)   # no point numbers
        new, old = readings[0]["id"], readings[1]["id"]
        return decision("propose_and_remeasure", rationale=f"Heart rate 105 to 112 ({old} to {new}): score 3 to 6, "
                        "YELLOW to ORANGE.", cited_ids=[old, new])
    turn1 = Reply("", tool_calls=[{"name": "fhir_search", "args": {"count": 5}},
                                  {"name": "check_deterioration", "args": {}},
                                  {"name": "get_queue_state", "args": {}}], tokens_in=900, tokens_out=40)
    backend.script("investigate", turn1, decide)
    out = two_readings(client, visit, heart_rate=112, temperature=38.6)
    p = card(client, visit)
    assert p["rationale_source"] == "model" and p["agent_action"] == "propose_and_remeasure"
    steps = trace(client, out["run_id"])
    names = [s["name"] for s in steps]
    after = names[names.index("trigger") + 1:names.index("submit_decision")]
    assert "search" in after and after.count("check_deterioration") == 1 and "get_queue_state" in after
    assert next(s for s in steps if s["name"] == "search")["server"] == "borrowed"
    sub = next(s for s in steps if s["name"] == "submit_decision")
    assert "rejected" not in sub["result_summary"]


def test_rationale_guidance_words_are_all_allowed_and_the_example_passes():
    for part in RATIONALE_WORDS.split(", "):
        assert all(w in VOCABULARY for w in part.casefold().replace("-", " ").split()), part
    facts = rationale_facts({"tews": 6}, {"tews": 3}, [105, 112, 37.2, 38.6],
                            ids=["Observation/11", "Observation/12"])
    assert rationale_text(RATIONALE_EXAMPLE, "code", facts) == (RATIONALE_EXAMPLE, "model", None)
    sign = rationale_facts(ids=["Observation/11"], chart={"signs": {"SOB_ACUTE": {"gloss": "sudden shortness"}}})
    assert rationale_text(RATIONALE_EXAMPLE_SIGN, "code", sign) == (RATIONALE_EXAMPLE_SIGN, "model", None)
    assert RATIONALE_WORDS in PROMPT and RATIONALE_EXAMPLE in PROMPT and RATIONALE_EXAMPLE_SIGN in PROMPT


def test_a_replaced_rationale_names_the_first_rejected_word():
    facts = rationale_facts({"tews": 6}, ids=["Observation/11"])
    assert rationale_text("Heart_rate rose, score 6.", "code", facts)[2] == \
        "word outside the allowed vocabulary: heart_rate"


def test_a_text_answer_gets_one_reminder_then_the_decision_counts(client, as_user, visit, backend):
    backend.script("investigate", Reply("I think the flag stands.", tokens_in=1, tokens_out=1),
                   decision("propose", rationale="Score 3 to 6, YELLOW to ORANGE."))
    out = two_readings(client, visit)
    sent = [x for x in backend.seen if x["purpose"] == "investigate"]
    assert len(sent) == 2 and sent[1]["messages"][-1]["role"] == "user"
    assert "submit_decision" in sent[1]["messages"][-1]["content"]
    sub = next(s for s in trace(client, out["run_id"]) if s["name"] == "submit_decision")
    assert card(client, visit)["rationale_source"] == "model" and "rejected" not in sub["result_summary"]


def test_two_text_answers_end_the_loop_with_the_code_proposal(client, as_user, visit, backend):
    text = Reply("no tool", tokens_in=1, tokens_out=1)
    backend.script("investigate", text, text, decision())
    two_readings(client, visit)
    assert len([x for x in backend.seen if x["purpose"] == "investigate"]) == 2
    p = card(client, visit)
    assert (p["agent_action"], p["rationale_source"], p["status"]) == ("propose", "code", "pending")
