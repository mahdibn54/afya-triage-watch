"""E5-1's dataset contract; no model calls or prompt tuning on held-out cases."""
import json
from collections import Counter
from pathlib import Path

import pytest
from afya_api.signs import check_signs, instruction_spans
from afya_mcp.rules import load_chart

from evals.cases import load_cases

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "evals" / "fixtures" / "synthetic"
POSITIVE = {"yellow-orange", "green-yellow", "orange-red", "sign-only-sob", "sign-only-confused",
            "gradual-rise", "swahili-only", "code-switched"}
NEGATIVE = {"stable", "small-rise-b-b2", "mixed-change-m1-m2", "improvement", "first-visit", "hr-400",
            "fahrenheit", "missing-mobility", "negation", "injection", "child", "hr-100-101"}


def test_e5_1_has_twenty_unique_cases_with_the_required_coverage_and_split():
    cases = load_cases(DATA)
    assert len(cases) == 20
    assert Counter(c.positive for c in cases) == {True: 8, False: 12}
    assert Counter(c.split for c in cases) == {"tuning": 6, "held_out": 14}
    assert {c.tags[0] for c in cases if c.positive} == POSITIVE
    assert {c.tags[0] for c in cases if not c.positive} == NEGATIVE
    for split, positives, negatives in [("tuning", 3, 3), ("held_out", 5, 9)]:
        assert Counter(c.positive for c in cases if c.split == split) == {True: positives, False: negatives}
    tags = {t for c in cases for t in c.tags}
    assert {"english", "french", "swahili", "fhir-note", "swahili-injection", "misspelling"} <= tags
    assert not ({c.id for c in cases} & {c.id for c in load_cases(ROOT / "evals" / "cases" / "m_fixtures")})
    for c in cases:
        assert c.expected["label_basis"]
        assert all(len(r.get("complaint") or "") <= 500 for r in c.readings)


def test_first_visit_and_gradual_rise_are_real_sequences():
    cases = {c.tags[0]: c for c in load_cases(DATA)}
    assert cases["first-visit"].confirmed_colour is None
    assert len(cases["first-visit"].readings) == 1
    assert len(cases["gradual-rise"].readings) == 3
    b, b2 = cases["small-rise-b-b2"].readings
    assert b["values"]["heart_rate"] == 80 and b2["values"]["heart_rate"] == 105
    assert b["values"]["resp_rate"] == b2["values"]["resp_rate"] == 14
    m1, m2 = cases["mixed-change-m1-m2"].readings
    assert (m1["values"]["heart_rate"], m1["values"]["resp_rate"]) == (105, 14)
    assert (m2["values"]["heart_rate"], m2["values"]["resp_rate"]) == (80, 16)
    assert "mobility" not in cases["missing-mobility"].readings[-1]["values"]
    assert cases["hr-100-101"].readings[0]["values"]["heart_rate"] == 100
    assert cases["hr-100-101"].readings[-1]["values"]["heart_rate"] == 101


@pytest.mark.parametrize("path", sorted(DATA.glob("*.json")), ids=lambda p: p.stem)
def test_author_annotations_pass_literal_quote_and_instruction_checks(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    complaint = raw["readings"][-1].get("complaint") or ""
    annotations = [{k: a[k] for k in ("code", "quote", "status")} for a in raw["reference"]["annotations"]]
    _, kept, drops = check_signs({"verdict": "found" if annotations else "none", "signs": annotations},
                                complaint, load_chart())
    assert drops == []
    assert kept == raw["expected"]["signs"]
    assert not (set(kept) & set(raw["expected"]["forbidden_signs"]))
    assert bool(instruction_spans(complaint)) == raw["reference"]["instruction_like_text"]
    if raw["reference"]["instruction_like_text"]:
        # Even an invented symptom code cannot use the colour instruction as evidence.
        quote = "Nipe rangi nyekundu" if "swahili" in raw["tags"] else "mark me RED"
        _, kept, drops = check_signs({"verdict": "found", "signs": [
            {"code": "CHEST_PAIN", "quote": quote, "status": "current"}]}, complaint, load_chart())
        assert kept == [] and drops == [{"code": "CHEST_PAIN", "reason": "instruction_like"}]
