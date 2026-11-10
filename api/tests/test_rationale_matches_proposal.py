"""The model's rationale is shown only when it agrees with the proposal card: it names the proposed colour, any colour
change it writes is confirmed -> proposed, and it names the warning sign that drove a sign proposal. Both texts below
were seen in the nurse-session eval (gpt-oss-120b) and are now replaced by the code-built sentence."""
from afya_mcp import rules

from afya_api.decision import RationaleFacts, facts_for, rationale_facts, rationale_text

CODE = "code sentence"
CHART = rules.load_chart()


def facts(colours, signs=(), **kw):
    base = rationale_facts({"tews": 1}, {"tews": 5}, [18, 24, 96, 124, 128, 86],
                           ids=["Observation/6410", "Observation/6411"], chart=CHART, **kw)
    names = tuple(frozenset({c.casefold(), CHART["signs"][c]["gloss"]}) for c in signs)
    return RationaleFacts(base.numbers, base.ids, base.words, base.order, colours, names)


def test_sign_proposal_text_that_says_green_to_green_is_replaced():
    f = facts(("GREEN", "ORANGE"), ["SEVERE_PAIN"])
    assert rationale_text("score 1 to 1 and GREEN to GREEN, no input changed.", CODE, f)[1] == "code"
    assert rationale_text("GREEN to GREEN, ORANGE proposed.", CODE, f)[2] == "colour change does not match the proposal"


def test_text_that_does_not_name_the_proposed_colour_is_replaced():
    assert rationale_text("Heart rate 96 to 124.", CODE, facts(("YELLOW", "ORANGE")))[2] == \
        "does not name the proposed colour"


def test_colour_change_must_start_from_the_confirmed_colour():
    text = "Heart rate 96 to 124: score 1 to 5, GREEN to ORANGE."
    assert rationale_text(text, CODE, facts(("YELLOW", "ORANGE")))[2] == "colour change does not match the proposal"
    ok = "Heart rate 96 to 124: score 1 to 5, YELLOW to ORANGE."
    assert rationale_text(ok, CODE, facts(("YELLOW", "ORANGE"))) == (ok, "model", None)


def test_sign_proposal_text_must_name_the_sign():
    f = facts(("GREEN", "ORANGE"), ["SEVERE_PAIN"])
    assert rationale_text("Heart rate 96 to 124, GREEN to ORANGE.", CODE, f)[2] == "does not name the warning sign"
    ok = "Warning sign SEVERE_PAIN reported; GREEN to ORANGE."
    assert rationale_text(ok, CODE, f) == (ok, "model", None)
    assert rationale_text("Severe pain reported; GREEN to ORANGE.", CODE, f)[1] == "model"   # the gloss counts


def test_facts_for_takes_colours_and_driving_signs_from_the_run():
    s = {"score": {"tews": 1, "observation_id": "2", "missing": []}, "det": {"confirmed_colour": "GREEN"},
         "trigger": {"kind": "sign", "from": "GREEN", "to": "ORANGE", "reasons": ["warning sign SEVERE_PAIN"]},
         "signs": {"kept": ["SEVERE_PAIN"], "rows": []}, "decision": {}}
    f = facts_for(s, CHART, [], [])
    assert f.colours == ("GREEN", "ORANGE") and f.signs == (frozenset({"severe_pain", "severe pain"}),)
    s["trigger"]["kind"] = "colour_rise"
    assert facts_for(s, CHART, [], []).signs == ()
