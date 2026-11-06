"""E5-6: the model's rationale is shown only if it passes the wording filter; otherwise a code-built sentence."""
from __future__ import annotations

import pytest
from fake_model import decision
from support import vitals

from afya_api.decision import rationale_facts, rationale_text

CODE = "Code sentence. Please take a second look."


@pytest.mark.parametrize("text", [
    "Likely sepsis: heart rate 105 to 112.", "Pattern suggests pneumonia.", "Rule out malaria.",
    "Possible infection.", "Diagnosis unclear.", "We suspect a chest problem.", "Give paracetamol 1 g.",
    "Administer 500 mg amoxicillin.", "Start antibiotics now.", "Fever caused by a virus.", "Treat with fluids.",
])
def test_denylisted_rationale_is_replaced_by_code(text):
    shown, source, why = rationale_text(text, CODE)
    assert (shown, source) == (CODE, "code") and why.startswith("denylist: ")


def test_clean_rationale_is_shown():
    text = "Heart rate 105 to 112 (Observation/1057) and temperature 37.2 to 38.6 raised the score from 3 to 6."
    facts = rationale_facts({"tews": 3}, {"tews": 6}, [{"before": {"obs_id": "Observation/1057", "value": 105},
                                                        "after": {"value": 112}}, {"before": {"value": 37.2},
                                                                                   "after": {"value": 38.6}}])
    assert rationale_text(text, CODE, facts) == (text, "model", None)
    assert rationale_text(text, CODE)[2] == "record id not in this run's evidence"   # no facts: nothing is allowed


def test_empty_or_too_long_rationale_falls_back():
    assert rationale_text("", CODE)[1:] == ("code", "no model rationale")
    assert rationale_text("Heart rate rose. " * 30, CODE)[1:] == ("code", "too long")


def card(client, visit):
    return [p for p in client.get("/proposals").json() if p["visit_id"] == visit][-1]


def test_in_the_graph_a_denylisted_rationale_is_replaced_and_logged(client, as_user, visit, backend):
    backend.script("investigate", decision("propose", rationale="Likely sepsis; give antibiotics."))
    r = vitals(client, visit)
    p = card(client, visit)
    assert p["rationale_source"] == "code" and "sepsis" not in p["rationale"]
    assert p["rationale"].endswith("Please take a second look.")
    step = next(s for s in client.get(f"/runs/{r.json()['run_id']}/trace").json() if s["name"] == "submit_decision")
    assert step["kind"] == "decision"
    from afya_mcp import db
    with db.connect() as c:
        row = c.execute("SELECT payload FROM audit_log WHERE run_id = %s AND kind = 'agent_step' "
                        "AND payload->>'name' = 'submit_decision'", (r.json()["run_id"],)).fetchone()
    assert row["payload"]["rationale_replaced"] == "denylist: likely" and row["payload"]["rationale_source"] == "code"


def test_in_the_graph_a_clean_rationale_is_shown(client, as_user, visit, backend):
    text = "Respiratory rate 26, heart rate 112 and temperature 38.6 moved the score to 6 (YELLOW to ORANGE)."
    backend.script("investigate", decision("propose", rationale=text))
    vitals(client, visit)
    p = card(client, visit)
    assert (p["rationale"], p["rationale_source"]) == (text, "model")
