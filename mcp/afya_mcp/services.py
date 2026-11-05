"""Tool logic for afya-mcp, independent of the MCP transport so it can be unit-tested with a fake FHIR store.

The MCP tools in server.py are thin wrappers around these functions.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from . import rules
from .fhir import REQ_SYSTEM, Fhir, age_years, confirmed_colour, observation_values, ref_id, vitals_observation


def record_vitals(fhir: Fhir, plausibility: dict[str, Any], patient_id: str, visit_id: str,
                  values: dict[str, Any], idempotency_key: str, when: datetime | None = None) -> dict[str, Any]:
    """E4-2. Plausibility first: anything impossible means nothing is saved and the nurse re-measures.

    Conditional create on the request identifier, so a retried call returns the same Observation.
    (Updating afya.visits.latest_obs_id happens in the Postgres layer, E3/E4-2 part 2.)
    """
    problems = rules.check_plausible(values, plausibility)
    if problems:
        return {"status": "remeasure", "saved": False, "problems": [asdict(p) for p in problems]}
    obs = vitals_observation(patient_id, visit_id, values, idempotency_key, when)
    created = fhir.conditional_create(obs, f"{REQ_SYSTEM}|{idempotency_key}")
    return {"status": "saved", "saved": True, "observation_id": f"Observation/{created['id']}"}


def compute_tews(fhir: Fhir, registry: list[dict[str, Any]], observation_id: str) -> dict[str, Any]:
    """E4-3. Takes only a record ID and reads the values itself, so the model can never mistype a vital sign."""
    oid = observation_id.split("/")[-1]
    obs = fhir.read("Observation", oid)
    patient = fhir.read("Patient", ref_id(obs["subject"]["reference"]))
    try:
        chart = rules.select_chart(age_years(patient), _height_cm(patient), registry)
    except rules.NoChartForPatient as e:
        return {"status": "no_chart", "observation_id": f"Observation/{oid}", "notice": str(e)}
    values = observation_values(obs)
    cited = {name: f"Observation/{oid}" for name in values}
    s = rules.score(values, chart, cited)
    return {"status": "scored", "observation_id": f"Observation/{oid}", "effective": obs.get("effectiveDateTime"),
            **asdict(s)}


def check_deterioration(fhir: Fhir, registry: list[dict[str, Any]], visit_id: str) -> dict[str, Any]:
    """E4-4. Latest reading vs the colour a nurse last confirmed (Encounter.priority), plus the previous reading.

    Returns the code-decided trigger without warning signs; the agent re-evaluates with validated signs later.
    """
    encounter = fhir.read("Encounter", visit_id)
    readings = fhir.search("Observation", {"encounter": f"Encounter/{visit_id}", "code": "85353-1",
                                           "_sort": "-date", "_count": "5"})
    if not readings:
        return {"status": "no_readings", "visit_id": visit_id}
    latest = compute_tews(fhir, registry, readings[0]["id"])
    if latest["status"] != "scored":
        return {"status": latest["status"], "visit_id": visit_id, "latest": latest}
    previous = compute_tews(fhir, registry, readings[1]["id"]) if len(readings) > 1 else None
    confirmed = confirmed_colour(encounter)
    chart = next(c for c in registry if c["chart_id"] == latest["chart_id"])
    after = rules.Score(**{k: latest[k] for k in rules.Score.__dataclass_fields__})
    trigger = rules.evaluate_trigger(confirmed, after, [], chart)
    changes = _changes(previous, latest) if previous and previous["status"] == "scored" else []
    return {
        "status": "checked",
        "visit_id": visit_id,
        "confirmed_colour": confirmed,
        "latest": {k: latest[k] for k in ("observation_id", "effective", "tews", "colour", "complete", "missing")},
        "previous": ({k: previous[k] for k in ("observation_id", "effective", "tews", "colour")}
                     if previous and previous["status"] == "scored" else None),
        "changes": changes,
        "trigger": {"kind": trigger.kind, "from": trigger.from_colour, "to": trigger.to_colour,
                    "reasons": trigger.reasons, "propose": trigger.propose},
    }


def _changes(previous: dict[str, Any], latest: dict[str, Any]) -> list[dict[str, Any]]:
    """Per input: points before and after, with the record behind each, for the evidence table on the card."""
    out = []
    for name, after in latest["points"].items():
        before = previous["points"].get(name)
        if before != after:
            out.append({"input": name, "points_before": before, "points_after": after,
                        "before": previous["cited"].get(name), "after": latest["cited"].get(name)})
    return out


def _height_cm(patient: dict[str, Any]) -> float | None:
    for ext in patient.get("extension", []):
        if ext.get("url") == "urn:afya:height-cm":
            return float(ext["valueDecimal"])
    return None
