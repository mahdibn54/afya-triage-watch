"""E1-5 plausibility check and E1-6 trigger rule."""
import pytest

from afya_mcp.rules import check_plausible, evaluate_trigger, load_chart, load_plausibility, score

CHART = load_chart()
LIMITS = load_plausibility()
BASE = dict(resp_rate=14, heart_rate=80, systolic_bp=120, temperature=37.0,
            mobility="walking", consciousness="alert", trauma="no")


def s(**changes):
    return score({**BASE, **changes}, CHART)


# ---------- plausibility ----------

def test_normal_values_are_plausible():
    assert check_plausible(BASE, LIMITS) == []


@pytest.mark.parametrize("name, value", [
    ("heart_rate", 400),          # typo or sensor error
    ("temperature", 101.0),       # entered in Fahrenheit
    ("temperature", 25.0),
    ("resp_rate", 0),
    ("systolic_bp", 20),
])
def test_impossible_values_are_rejected(name, value):
    problems = check_plausible({**BASE, name: value}, LIMITS)
    assert [p.name for p in problems] == [name]


def test_missing_values_are_not_a_plausibility_problem():
    values = dict(BASE)
    del values["heart_rate"]
    assert check_plausible(values, LIMITS) == []


# ---------- trigger rule ----------

def test_first_reading_is_baseline_only():
    t = evaluate_trigger(None, s(resp_rate=30, heart_rate=135, mobility="with_help"), [], CHART)
    assert not t.propose and t.reasons == ["first reading: baseline only"]


def test_p014_yellow_to_orange_is_a_colour_rise():
    after = s(resp_rate=26, heart_rate=112, temperature=38.6)          # TEWS 6
    t = evaluate_trigger("YELLOW", after, ["SOB_ACUTE"], CHART)
    assert (t.kind, t.from_colour, t.to_colour) == ("colour_rise", "YELLOW", "ORANGE")


def test_small_rise_within_green_is_logged_only():                     # B -> B2
    t = evaluate_trigger("GREEN", s(heart_rate=105), [], CHART)
    assert not t.propose and t.to_colour == "GREEN"


def test_mixed_change_is_logged_only():                                # M1 -> M2
    t = evaluate_trigger("GREEN", s(heart_rate=80, resp_rate=16), [], CHART)
    assert not t.propose


def test_improvement_is_never_a_downgrade():
    t = evaluate_trigger("ORANGE", s(), [], CHART)                     # now TEWS 0
    assert not t.propose
    assert t.to_colour == "ORANGE"
    assert "never downgraded" in t.reasons[0]


def test_confused_input_raises_green_to_orange():                      # fixture C
    t = evaluate_trigger("GREEN", s(consciousness="confused"), [], CHART)
    assert (t.kind, t.to_colour) == ("colour_rise", "ORANGE")


def test_urgent_sign_with_stable_vitals_triggers():
    t = evaluate_trigger("GREEN", s(), ["SOB_ACUTE"], CHART)
    assert (t.kind, t.to_colour) == ("sign", "ORANGE")


def test_red_sign_proposes_red():
    t = evaluate_trigger("YELLOW", s(), ["SEIZURE_CURRENT"], CHART)
    assert (t.kind, t.to_colour) == ("sign", "RED")


def test_yellow_sign_alone_does_not_trigger():
    t = evaluate_trigger("GREEN", s(), ["ABDOMINAL_PAIN"], CHART)
    assert not t.propose


def test_sign_not_above_confirmed_colour_does_not_trigger():
    t = evaluate_trigger("ORANGE", s(), ["SOB_ACUTE"], CHART)
    assert not t.propose


def test_nurse_reported_worsening_triggers():
    t = evaluate_trigger("YELLOW", s(), [], CHART, nurse_reported_worsening=True)
    assert (t.kind, t.to_colour) == ("nurse_reported", "YELLOW")


def test_incomplete_score_still_triggers_and_says_so():
    values = {**BASE, "resp_rate": 30, "heart_rate": 135}
    del values["mobility"]
    t = evaluate_trigger("GREEN", score(values, CHART), [], CHART)
    assert t.kind == "colour_rise" and any("lower bound" in r for r in t.reasons)


def test_unknown_sign_code_is_rejected():
    with pytest.raises(ValueError):
        evaluate_trigger("GREEN", s(), ["MAKE_ME_GREEN"], CHART)
