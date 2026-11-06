"""Replay the E5-1 inputs through real recording/scoring/trigger code using in-memory FHIR.

Complaint annotations are author labels, never model predictions; their human review is tracked in the backlog.
"""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from afya_mcp import rules, services
from afya_mcp.fhir import observation_values
from fake_fhir import FakeFhir

DATA = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "synthetic"
FILES = sorted(DATA.glob("*.json"))
REG, LIMITS = rules.load_registry(), rules.load_plausibility()


def test_synthetic_dataset_exists():
    assert len(FILES) == 20


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_synthetic_labels_match_recording_scoring_and_trigger(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    fhir = FakeFhir()
    born = date(date.today().year - raw["age_years"], 1, 1).isoformat()
    visit = services.seed_demo_visit(fhir, raw["id"], born, raw["arrived_minutes_ago"], raw["confirmed_colour"])
    assert visit["status"] == "seeded"
    refs = raw["reference"]["readings"]
    assert len(refs) == len(raw["readings"])
    checked = None
    now = datetime.now(timezone.utc)
    for i, (reading, ref) in enumerate(zip(raw["readings"], refs, strict=True)):
        created_before = fhir.creates
        saved = services.record_vitals(fhir, LIMITS, REG, None, visit["visit_id"], reading["values"],
                                      f"{raw['id']}-{i}", when=now + timedelta(seconds=i),
                                      complaint=reading.get("complaint"))
        if ref["status"] == "remeasure":
            assert saved["status"] == "remeasure" and not saved["saved"]
            assert {p["name"] for p in saved["problems"]} == set(ref["problems"])
            assert fhir.creates == created_before
            checked = None
            break
        assert saved["status"] == "saved"
        obs = fhir.read("Observation", saved["observation_id"].split("/")[-1])
        assert observation_values(obs) == reading["values"]
        scored = services.compute_tews(fhir, REG, saved["observation_id"])
        assert scored["status"] == ref["status"]
        checked = services.check_deterioration(fhir, REG, visit["visit_id"])
        if ref["status"] == "no_chart":
            assert checked["status"] == "no_chart"
            break
        assert (scored["tews"], scored["colour"]) == (ref["tews"], ref["colour"])
        assert scored["missing"] == ref.get("missing", [])
        assert scored["complete"] == (not ref.get("missing"))

    assert fhir.search("Flag", {}) == []
    encounter = fhir.read("Encounter", visit["visit_id"])
    if raw["confirmed_colour"] is None:
        assert "priority" not in encounter
    else:
        assert encounter["priority"]["coding"][0]["code"] == raw["confirmed_colour"]
    expected, reference = raw["expected"], raw["reference"]
    if checked is None or checked["status"] == "no_chart":
        assert expected["proposal"] is False
        return
    chart = next(c for c in REG if c["chart_id"] == scored["chart_id"])
    after = rules.Score(**{k: scored[k] for k in rules.Score.__dataclass_fields__})
    previous = checked["previous"]
    result = rules.evaluate_trigger(raw["confirmed_colour"], after, expected.get("signs", []), chart,
                                    previous_colour=previous["colour"] if previous else None)
    assert result.propose == expected["proposal"]
    assert (result.kind, result.to_colour) == (reference["trigger_kind"], reference["trigger_colour"])
    if result.propose:
        assert result.to_colour == expected["to_colour"]
    # Author-labelled complaint signs can add urgency above the rules-only path.
    assert rules.COLOUR_RANK[checked["trigger"]["to"]] <= rules.COLOUR_RANK[result.to_colour]
