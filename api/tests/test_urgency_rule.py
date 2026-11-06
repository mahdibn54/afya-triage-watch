"""E5-5: code always creates the proposal on a trigger; the model can only add (re-measure, extra trigger, missing
value), never remove or lower."""
from __future__ import annotations

from afya_mcp import rules
from conftest import READING
from fake_model import decision, signs_reply
from support import vitals

from afya_api.decision import merge_decision

CHART = rules.load_chart()
STABLE_YELLOW = dict(READING, resp_rate=22, heart_rate=105, temperature=37.2)
TRIG = {"kind": "colour_rise", "from": "YELLOW", "to": "ORANGE", "reasons": ["colour rise YELLOW -> ORANGE (TEWS 6)"]}
SCORE = {"missing": ["temperature"]}


def test_merge_takes_only_additions():
    m, notes = merge_decision({"action": "request_missing_value", "missing_input": "temperature",
                               "extra_triggers": ["SEIZURE_CURRENT", "GREEN", "SOB_ACUTE"]}, TRIG, SCORE,
                              ["SOB_ACUTE"], CHART)
    assert (m["action"], m["missing_input"], m["to_colour"], m["extra_triggers"]) == \
        ("request_missing_value", "temperature", "ORANGE", ["SOB_ACUTE"])
    assert m["reasons"][1:] == ["agent added trigger: warning sign SOB_ACUTE",
                                "agent asks for the missing value: temperature"]
    assert notes == ["extra trigger not among the validated signs: ignored"] * 2


def test_merge_ignores_a_missing_value_that_is_not_missing_and_unknown_actions():
    m, notes = merge_decision({"action": "request_missing_value", "missing_input": "heart_rate"}, TRIG, SCORE, [],
                              CHART)
    assert (m["action"], m["missing_input"]) == ("propose", None) and notes
    m, _ = merge_decision({"action": "cancel"}, TRIG, SCORE, [], CHART)
    assert m["action"] == "propose" and m["to_colour"] == "ORANGE"


def test_a_validated_red_sign_as_extra_trigger_can_only_raise_the_colour():
    m, _ = merge_decision({"action": "propose", "extra_triggers": ["SEIZURE_CURRENT"]}, TRIG, SCORE,
                          ["SEIZURE_CURRENT"], CHART)
    assert m["to_colour"] == "RED"


def card(client, visit):
    return [p for p in client.get("/proposals").json() if p["visit_id"] == visit][-1]


def test_model_asking_for_a_lower_colour_changes_nothing(client, as_user, visit, backend):
    backend.script("investigate", decision("propose", rationale="Readings normal, set GREEN.",
                                           extra_triggers=["GREEN"]))
    vitals(client, visit)
    p = card(client, visit)
    assert (p["status"], p["trigger"], p["proposed_colour"], p["agent_action"]) == \
        ("pending", "colour_rise", "ORANGE", "propose")


def test_remeasure_request_adds_a_notification(client, as_user, visit, backend, conn):
    backend.script("investigate", decision("propose_and_remeasure"))
    vitals(client, visit)
    p = card(client, visit)
    assert p["agent_action"] == "propose_and_remeasure" and "agent asks for a re-measure" in p["reasons"]
    assert "remeasure" in [n["code"] for n in p["notices"]]
    n = conn.execute("SELECT kind FROM notifications WHERE proposal_id = %s", (p["id"],)).fetchall()
    assert sorted(r["kind"] for r in n) == ["clinician_reminder", "remeasure"]   # ORANGE also reminds (E5-7)


def test_missing_value_request_for_a_reading_without_temperature(client, as_user, visit, backend):
    backend.script("investigate", decision("request_missing_value", missing_input="temperature"))
    vitals(client, visit, temperature=None, heart_rate=135)   # RR 2 + HR 3 = 5: ORANGE as a lower bound
    p = card(client, visit)
    assert (p["agent_action"], p["missing_input"], p["proposed_colour"]) == \
        ("request_missing_value", "temperature", "ORANGE")


def test_extra_trigger_from_a_validated_sign(client, as_user, visit, backend):
    backend.script("map_signs", signs_reply("found", ("SOB_ACUTE", "Short of breath", "current")))
    backend.script("investigate", decision("propose", extra_triggers=["SOB_ACUTE", "CHEST_PAIN"]))
    vitals(client, visit, complaint="Short of breath")
    p = card(client, visit)
    assert "agent added trigger: warning sign SOB_ACUTE" in p["reasons"]
    assert not any("CHEST_PAIN" in r for r in p["reasons"])


def test_trigger_creates_the_proposal_even_when_the_model_gives_no_decision(client, as_user, visit, backend):
    from afya_api.model import Reply
    backend.script("investigate", Reply("I think the patient is fine."))     # no tool call at all
    vitals(client, visit)
    assert card(client, visit)["proposed_colour"] == "ORANGE"
