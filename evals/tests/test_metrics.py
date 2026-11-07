"""Unit tests for the eval statistics and metrics (no stack, no model). Run: make eval-test"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from evals import metrics, report, stats
from evals.cases import CaseError, load_cases, parse_case
from evals.wording import violations

ROOT = Path(__file__).resolve().parents[2]


# ---- stats ----

def test_wilson_known_values():
    lo, hi = stats.wilson(5, 10)
    assert (lo, hi) == pytest.approx((0.2366, 0.7634), abs=1e-3)
    lo, hi = stats.wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = stats.wilson(10, 10)
    assert hi == pytest.approx(1.0) and lo == pytest.approx(0.7225, abs=1e-3)
    lo, hi = stats.wilson(95, 100)
    assert (lo, hi) == pytest.approx((0.8884, 0.9784), abs=1e-3)


def test_wilson_edges_and_bounds():
    assert stats.wilson(0, 0) == (0.0, 1.0)
    for k, n in [(0, 1), (1, 1), (3, 7), (50, 50)]:
        lo, hi = stats.wilson(k, n)
        assert 0 <= lo <= k / n <= hi <= 1
    with pytest.raises(ValueError):
        stats.wilson(3, 2)
    with pytest.raises(ValueError):
        stats.wilson(-1, 2)


def test_wilson_narrows_with_n():
    w10 = stats.wilson(9, 10)
    w100 = stats.wilson(90, 100)
    assert (w100[1] - w100[0]) < (w10[1] - w10[0])


def test_fmt_kn():
    assert stats.fmt_kn(0, 0).startswith("n/a")
    s = stats.fmt_kn(5, 10)
    assert s.startswith("5/10 (50%") and "24-76%" in s


def test_percentiles():
    assert stats.median([]) is None
    assert stats.median([3, 1, 2]) == 2
    assert stats.median([1, 2, 3, 4]) == 2.5
    assert stats.p95([10]) == 10
    assert stats.p95(list(range(1, 101))) == pytest.approx(95.05)
    assert math.isclose(stats.percentile([0, 10], 25), 2.5)
    with pytest.raises(ValueError):
        stats.percentile([1], 101)


# ---- wording ----

def test_wording_flags_diagnosis_and_treatment():
    assert violations("Likely pneumonia, give oxygen") == ["likely", "pneumonia", "give", "oxygen"]
    assert violations("Heart rate 105 to 112: the score moved from 3 to 6 (YELLOW to ORANGE).") == []
    assert violations(None) == []
    assert "mg" in violations("500 mg")
    assert violations("Amount of change") == []   # word boundaries: no hit inside 'amount'


# ---- cases ----

def good_case(**over):
    base = {"id": "c1", "synthetic": True, "age_years": 40, "confirmed_colour": "GREEN",
            "readings": [{"values": {"heart_rate": 80}, "complaint": None}], "expected": {"proposal": False}}
    return {**base, **over}


def test_parse_case_ok_and_defaults():
    c = parse_case(good_case())
    assert c.split == "fixture" and not c.positive and c.expected["signs"] == []


@pytest.mark.parametrize("bad", [
    {"synthetic": False}, {"id": "has space"}, {"confirmed_colour": "BLUE"}, {"readings": []},
    {"readings": [{"values": {"pulse": 1}}]}, {"expected": {"proposal": True}}, {"split": "dev"},
    {"expected": {"proposal": False, "signs": "SOB"}},
])
def test_parse_case_rejects(bad):
    with pytest.raises(CaseError):
        parse_case(good_case(**bad))


def test_load_m_fixtures_are_valid_and_cover_the_required_cases():
    cases = load_cases(ROOT / "evals" / "cases" / "m_fixtures")
    assert len(cases) >= 12 and len({c.id for c in cases}) == len(cases)
    tags = {t for c in cases for t in c.tags}
    assert {"p014", "negation", "injection", "swahili", "fhir-note", "sign-from-reading"} <= tags
    assert all(c.split == "fixture" for c in cases)


# ---- metrics ----

def trial(case="c", model="m", proposal=None, expected=None, **kw):
    exp = {"proposal": False, "to_colour": None, "signs": [], "forbidden_signs": [], "notices": []}
    exp.update(expected or {})
    t = {"trial_id": f"{model}-{case}-{kw.pop('i', 1)}", "case_id": case, "model": model, "group": "B", "split": "fixture",
         "set": "s", "expected": exp, "proposal": proposal, "decision": None, "trace": [], "visit_obs_ids": ["Observation/1", "Observation/2"],
         "ungated": [], "error": None, "run_status": "paused" if proposal else "ended"}
    t.update(kw)
    return t


def card(colour="ORANGE", signs=(), rationale="Heart rate 80 to 112.", cited=("Observation/1", "Observation/2"), notices=()):
    return {"to_colour": colour, "agent_action": "propose", "rationale": rationale, "rationale_source": "model",
            "signs": [{"code": c, "status": "current", "source": "complaint"} for c in signs],
            "cited_obs_ids": list(cited), "notices": [{"code": n} for n in notices]}


def test_outcome_correct_and_error_kinds():
    pos = {"proposal": True, "to_colour": "ORANGE"}
    assert metrics.outcome_correct(trial(proposal=card("ORANGE"), expected=pos))
    assert not metrics.outcome_correct(trial(proposal=card("YELLOW"), expected=pos))
    assert metrics.under_called(trial(proposal=card("YELLOW"), expected=pos))
    assert not metrics.under_called(trial(proposal=card("RED"), expected=pos))
    assert metrics.missed(trial(expected=pos))
    assert not metrics.outcome_correct(trial(expected=pos))
    assert metrics.false_alert(trial(proposal=card()))
    assert metrics.outcome_correct(trial())
    assert not metrics.outcome_correct(trial(error="ConnectError"))
    assert not metrics.missed(trial(expected=pos, error="ConnectError"))   # a failed run is not a miss


def test_sign_precision_recall_counts():
    a = trial(proposal=card(signs=["SOB_ACUTE", "CHEST_PAIN"]), expected={"proposal": True, "to_colour": "ORANGE",
                                                                         "signs": ["SOB_ACUTE"], "forbidden_signs": ["CHEST_PAIN"]})
    b = trial(expected={"signs": ["SOB_ACUTE"]}, kept_signs=[])     # no proposal, sign missed
    c = trial(expected={"signs": []}, kept_signs=["COUGHING_BLOOD"])  # no proposal, sign wrongly kept
    assert metrics.sign_counts([a, b, c]) == (1, 2, 1)
    assert metrics.forbidden_sign_hits(a) == ["CHEST_PAIN"]


def test_a_reading_sign_is_not_a_complaint_sign():
    p = card()
    p["signs"] = [{"code": "LOC_REDUCED_CONFUSED", "status": "current", "source": "reading"}]
    assert metrics.complaint_signs(trial(proposal=p)) == set()
    p["signs"] = [{"code": "CHEST_PAIN", "status": "other", "source": "complaint"}]   # greyed mention: not kept
    assert metrics.complaint_signs(trial(proposal=p)) == set()


def test_ungated_and_rationale_and_citations():
    assert metrics.ungated_count(trial(ungated=["raise_recheck_flag", "command_row"])) == 2
    assert metrics.ungated_count(trial()) == 0
    assert metrics.rationale_violations(trial(proposal=card(rationale="Likely sepsis, give fluids"))) == ["likely", "sepsis", "give", "fluids"]
    assert metrics.rationale_violations(trial()) == []
    assert metrics.payload_citations_valid(trial(proposal=card())) is True
    assert metrics.payload_citations_valid(trial(proposal=card(cited=["Observation/9"]))) is False
    assert metrics.payload_citations_valid(trial()) is None
    d = {"cited_ids": ["Observation/1"], "rejected_cited_ids": 2, "model_decision": "ok"}
    assert metrics.model_bad_citations(trial(decision=d)) == 2 and metrics.model_decided(trial(decision=d))
    assert metrics.model_bad_citations(trial()) == 0


def test_rationale_filter_counts():
    given = trial(proposal=card(), decision={"rationale_replaced": "denylist: likely"})
    ok = trial(proposal=card(), decision={"rationale_replaced": None})
    none = trial(proposal=card(), decision={"rationale_replaced": "no model rationale"})
    assert metrics.rationale_given(given) and metrics.rationale_filtered(given)
    assert metrics.rationale_given(ok) and not metrics.rationale_filtered(ok)
    assert not metrics.rationale_given(none) and not metrics.rationale_filtered(none)


def step(name, kind="tool", result="ok"):
    return {"name": name, "step_kind": kind, "result": result}


GOOD = [step("validate", "gate"), step("record_vitals"), step("compute_tews"), step("check_deterioration"),
        step("map_signs", "model"), step("trigger", "decision"), step("investigate", "model"), step("search"),
        step("investigate", "model"), step("submit_decision", "decision"), step("paused_for_nurse", "gate")]


def test_tool_order_good_trace_and_violations():
    assert metrics.tool_order_violations(trial(trace=GOOD)) == []
    assert metrics.tool_order_violations(trial(trace=[])) == []
    swapped = [GOOD[0], GOOD[1], GOOD[3], GOOD[2], *GOOD[4:]]
    assert any("came before" in v for v in metrics.tool_order_violations(trial(trace=swapped)))
    many = GOOD[:6] + [step("search")] * 5 + GOOD[9:]
    assert any("read-only tool calls" in v for v in metrics.tool_order_violations(trial(trace=many)))
    after = [*GOOD[:10], step("search"), GOOD[10]]
    assert any("after submit_decision" in v for v in metrics.tool_order_violations(trial(trace=after)))
    refused = [*GOOD[:7], step("raise_recheck_flag", result="refused: not an offered tool (read-only list)"), *GOOD[7:]]
    v = metrics.tool_order_violations(trial(trace=refused))
    assert any("refused" in x for x in v) and any("write tool" in x for x in v)
    two = [*GOOD[:10], step("submit_decision", "decision"), GOOD[10]]
    assert any("more than one" in x for x in metrics.tool_order_violations(trial(trace=two)))



def test_intent_rows_count_as_their_tool():
    # E12-2: afya-mcp writes `<tool>_started` before an act tool; a reminder after the pause is allowed, a write
    # intent before approval is still a write.
    reminder = [*GOOD, step("notify_staff_started"), step("notify_staff")]
    assert metrics.tool_order_violations(trial(trace=reminder)) == []
    write = [*GOOD[:7], step("raise_recheck_flag_started"), *GOOD[7:]]
    assert any("write tool" in x for x in metrics.tool_order_violations(trial(trace=write)))

def test_disagreement_between_runs():
    a1 = trial(case="a", proposal=card("ORANGE"), i=1)
    a2 = trial(case="a", proposal=card("ORANGE"), i=2)
    b1 = trial(case="b", proposal=card("ORANGE"), i=1)
    b2 = trial(case="b", i=2)
    c1 = trial(case="c", i=1)
    assert metrics.disagreeing_cases([a1, a2, b1, b2, c1]) == (1, 2, ["b"])   # c has one run: not counted
    assert metrics.disagreeing_cases([]) == (0, 0, [])


def test_case_level_majority():
    assert metrics.majority([True, True, False]) and not metrics.majority([True, False])
    exp = {"proposal": False, "to_colour": None, "signs": []}
    runs = [trial(case="x", i=i, expected=exp, proposal=card() if i < 3 else None) for i in range(5)]   # 3 of 5 false alerts
    one = [trial(case="y", i=i, expected=exp, proposal=card() if i < 2 else None) for i in range(5)]    # 2 of 5
    c = metrics.case_counts(runs + one)
    assert c["false_alerts"] == (1, 2) and c["outcome_correct"] == (1, 2) and c["sensitivity"] == (0, 0)


def test_summarize_and_report_build():
    pos = {"proposal": True, "to_colour": "ORANGE", "signs": ["SOB_ACUTE"]}
    ts = [trial(case="p", proposal=card(signs=["SOB_ACUTE"]), expected=pos, trace=GOOD, tokens_in=1000, tokens_out=50,
                model_latency_ms=2000.0, wall_ms=5000.0, cost_usd=0, decision={"rationale_replaced": None, "model_decision": "ok", "rejected_cited_ids": 0}),
          trial(case="n", i=1, trace=GOOD[:6], tokens_in=0, tokens_out=0, wall_ms=100.0, cost_usd=0),
          trial(case="n", i=2, proposal=card(), trace=GOOD, wall_ms=300.0, cost_usd=0)]
    x = metrics.summarize(ts)
    assert x["outcome_correct"] == (2, 3) and x["sensitivity"] == (1, 1) and x["false_alerts"] == (1, 2)
    assert x["sign_precision"] == (1, 1) and x["sign_recall"] == (1, 1) and x["ungated_actions"] == 0
    assert x["runs_disagree"][:2] == (1, 1) and x["tool_order_violations"] == (0, 3)
    assert x["speed"]["tokens_in_median"] == 1000 and x["speed"]["cost_usd_total"] == 0
    c = x["case_level"]       # n = cases; case "n" has a tie (1 of 2 runs wrong): not a majority, so not a false alert
    assert c["outcome_correct"] == (1, 2) or c["outcome_correct"] == (2, 2)
    assert c["sensitivity"] == (1, 1) and c["false_alerts"] == (0, 1)
    for t in ts:
        t.update({"group": "B", "batch": "b", "code_commit": "abc", "_file": "f.jsonl", "_line": 1, "run_id": "1:2", "tags": []})
    md = report.build(ts)
    for head in ("Runs in the logs", "Headline, case level", "Trial level, secondary", "Rules-only baseline", "Per case", "Worst case"):
        assert head in md
    assert "1/2 (50%" in md   # false alerts k/n with its interval


def test_report_rewrite_keeps_the_text_around_the_block(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    md = tmp_path / "EVALS.md"
    md.write_text(f"intro\n\n{report.BEGIN}\nold\n{report.END}\n\nafter\n", encoding="utf-8")
    report.rewrite(md, runs)
    text = md.read_text(encoding="utf-8")
    assert text.startswith("intro") and text.rstrip().endswith("after") and "old" not in text
    assert "No runs logged yet" in text


def test_worst_table_orders_by_failure_rate_and_points_into_the_log():
    pos = {"proposal": True, "to_colour": "ORANGE"}

    def mk(case, i, ok):
        t = trial(case=case, i=i, proposal=card() if ok else None, expected=pos)
        t.update({"set": "s", "run_id": f"v:{case}{i}", "_file": "f.jsonl", "_line": i})
        return t

    ts = [mk("easy", 1, True), mk("easy", 2, False), mk("hard", 1, False), mk("hard", 2, False), mk("fine", 1, True)]
    md = report.worst_table(ts)
    assert md.index("`hard`") < md.index("`easy`") and "fine" not in md
    assert "v:hard1" in md and "f.jsonl:1" in md
    assert report.worst_table([mk("ok", 1, True)]) == "No trial differed from its label."


def test_notice_missing_only_counts_when_there_is_a_card():
    exp = {"proposal": True, "to_colour": "ORANGE", "notices": ["instruction_like_text"]}
    assert metrics.notice_missing(trial(proposal=card(notices=["instruction_like_text"]), expected=exp)) == []
    assert metrics.notice_missing(trial(proposal=card(), expected=exp)) == ["instruction_like_text"]
    assert metrics.notice_missing(trial(expected=exp)) == []   # no card: not observable


def test_model_chosen_reads_own_vs_borrowed_and_turns():
    """E12-5: reads between the code's trigger and submit_decision are the model's; the graph's own compute_tews and
    check_deterioration before the trigger are not counted."""
    def turn(n):
        return {**step("investigate", "model"), "args": f"turn {n}"}
    borrowed = {**step("search"), "server": "borrowed"}
    own = {**step("get_queue_state"), "server": "ours"}
    rows = [*GOOD[:6], turn(1), borrowed, own, {**step("check_deterioration"), "server": "ours"}, turn(2),
            GOOD[9], GOOD[10]]
    deep = trial(case="a", proposal=card(), trace=rows, decision={"model_decision": "ok"})
    quick = trial(case="b", proposal=card(), trace=[*GOOD[:6], turn(1), GOOD[9], GOOD[10]],
                  decision={"model_decision": "ok"})
    none = trial(case="c", trace=GOOD[:6])
    assert metrics.model_reads(deep) == (2, 1) and metrics.investigate_turns(deep) == 2
    assert metrics.model_reads(quick) == (0, 0) and metrics.model_reads(none) == (0, 0)
    x = metrics.investigation_summary([deep, quick, none])
    assert x["loops"] == 2 and x["loops_with_reads"] == (1, 2) and x["loops_with_own_and_borrowed"] == (1, 2)
    assert (x["own_reads"], x["borrowed_reads"]) == (2, 1) and x["turns_max"] == 2
    assert x["decided_on_turn_1"] == (1, 2) and x["valid_model_decisions"] == (2, 2)
    for t in (deep, quick, none):
        t.update({"batch": "b", "code_commit": "c", "_file": "f.jsonl", "_line": 1, "run_id": "1:2", "tags": []})
    assert "Model-chosen investigation" in report.build([deep, quick, none])


def test_report_keeps_two_batches_of_one_model_apart():
    a = trial(case="a", batch="b1", code_commit="c1", _file="f", _line=1, tags=[])
    b = trial(case="a", i=2, batch="b2", code_commit="c2", _file="g", _line=1, tags=[])
    md = report.build([a, b])
    assert "`m @ b1`" in md and "`m @ b2`" in md
