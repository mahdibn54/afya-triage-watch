"""E2-4: the pinned WSO2 0.11.0 FHIRPath projection and its response adapter.

WSO2 returns dotted expression keys and flattened Bundle entries, not nested FHIR. Select quantities separately
by LOINC code: projecting parallel arrays over all components would misassociate values when a field is absent.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

PANEL = "85353-1"
LOINC_ALLOW = {"9279-1": "resp_rate", "8867-4": "heart_rate", "8480-6": "systolic_bp", "8310-5": "temperature",
               "59408-5": "spo2"}
UCUM = "http://unitsofmeasure.org"
UNIT_ALLOW = {"9279-1": {"/min"}, "8867-4": {"/min"}, "8480-6": {"mm[Hg]"}, "8310-5": {"Cel", "[degF]"},
              "59408-5": {"%"}}
PANEL_PATH = f"code.coding.where(system='http://loinc.org' and code='{PANEL}').code"
NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


def quantity_path(code: str, field: str) -> str:
    return (f"component.where(code.coding.where(system='http://loinc.org' and code='{code}').exists())"
            f".valueQuantity.{field}")


FHIRPATHS = ("Bundle.type", "Observation.id", "Observation.resourceType", "Observation.encounter.reference",
             "Observation.effectiveDateTime", f"Observation.{PANEL_PATH}",
             *(f"Observation.{quantity_path(code, field)}"
               for code in LOINC_ALLOW for field in ("value", "system", "code")))


def _observation(row: dict[str, Any]) -> dict[str, Any]:
    if (row.get("_errors") or row.get("resourceType") != "Observation"
            or not isinstance(row.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", row["id"])
            or row.get(PANEL_PATH) != PANEL or not isinstance(row.get("encounter.reference"), str)):
        raise ValueError("unexpected WSO2 Observation projection")
    components = []
    for code in LOINC_ALLOW:
        fields = {field: row.get(quantity_path(code, field), []) for field in ("value", "system", "code")}
        # Duplicate components or unequal optional fields are ambiguous; never pair them by array position.
        if any(not isinstance(v, list) or len(v) > 1 for v in fields.values()) or len(fields["value"]) != 1:
            continue
        value = fields["value"][0]
        # The pinned MCP server serializes FHIRPath Decimal results as strings (verified against real HAPI).
        if isinstance(value, str):
            if len(value) > 64 or not NUMBER.fullmatch(value):
                continue
            value = json.loads(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        quantity = {"value": value, **{k: v[0] for k, v in fields.items() if k != "value" and v}}
        components.append({"code": {"coding": [{"system": "http://loinc.org", "code": code}]},
                           "valueQuantity": quantity})
    return {"resourceType": "Observation", "id": row["id"],
            "encounter": {"reference": row["encounter.reference"]},
            "effectiveDateTime": row.get("effectiveDateTime"),
            "code": {"coding": [{"system": "http://loinc.org", "code": PANEL}]}, "component": components}


def restore_response(tool: str, data: dict[str, Any]) -> dict[str, Any]:
    """Restore only the projected fields to the Gateway's existing FHIR-shaped contract.

    The encounter reference is internal evidence for the visit check, never part of model output. Arbitrary fields,
    narrative, notes, identifiers, display strings, Bundle links and WSO2 diagnostics are not carried through.
    """
    if not isinstance(data, dict) or data.get("_errors"):
        raise ValueError("unexpected WSO2 projection")
    if tool == "read":
        return _observation(data)
    if tool != "search" or data.get("type") != "searchset" or not isinstance(data.get("entry", []), list):
        raise ValueError("unexpected WSO2 search projection")
    return {"resourceType": "Bundle", "entry": [{"resource": _observation(row)} for row in data.get("entry", [])]}
