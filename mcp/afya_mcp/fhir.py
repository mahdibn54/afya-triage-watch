"""Minimal FHIR R4 access for afya-mcp, plus the mapping between our vitals and FHIR Observations.

One reading = one Observation (LOINC 85353-1 vital signs panel) with one component per input.
Its business identifier (urn:afya:req|<idempotency key>) makes creation idempotent (conditional create).
The confirmed SATS colour of a visit lives on Encounter.priority (system urn:afya:sats-colour).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Protocol

import httpx

REQ_SYSTEM = "urn:afya:req"
COLOUR_SYSTEM = "urn:afya:sats-colour"
LOINC = "http://loinc.org"
AFYA = "urn:afya:codes"

# input name -> (system, code, unit or None for coded values)
COMPONENTS: dict[str, tuple[str, str, str | None]] = {
    "resp_rate": (LOINC, "9279-1", "/min"),
    "heart_rate": (LOINC, "8867-4", "/min"),
    "systolic_bp": (LOINC, "8480-6", "mm[Hg]"),
    "temperature": (LOINC, "8310-5", "Cel"),
    "spo2": (LOINC, "59408-5", "%"),
    "mobility": (AFYA, "mobility", None),
    "consciousness": (AFYA, "avpu", None),
    "trauma": (AFYA, "trauma", None),
}
_BY_CODE = {code: name for name, (_s, code, _u) in COMPONENTS.items()}


class Fhir(Protocol):
    def read(self, rtype: str, rid: str) -> dict[str, Any]: ...
    def search(self, rtype: str, params: dict[str, str]) -> list[dict[str, Any]]: ...
    def conditional_create(self, resource: dict[str, Any], identifier: str) -> dict[str, Any]: ...
    def update(self, resource: dict[str, Any]) -> dict[str, Any]: ...


class FhirUnavailable(Exception):
    """FHIR server down or timing out (the agent retries, then warns the nurse)."""


class HttpFhir:
    """Talks to HAPI on the internal, write-capable URL. Never handed to the model."""

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.client = httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=timeout,
                                   headers={"Accept": "application/fhir+json"})

    def _call(self, method: str, url: str, **kw: Any) -> httpx.Response:
        try:
            r = self.client.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise FhirUnavailable(str(e)) from e
        if r.status_code >= 500:
            raise FhirUnavailable(f"{method} {url}: HTTP {r.status_code}")
        r.raise_for_status()
        return r

    def read(self, rtype: str, rid: str) -> dict[str, Any]:
        return self._call("GET", f"{rtype}/{rid}").json()

    def search(self, rtype: str, params: dict[str, str]) -> list[dict[str, Any]]:
        bundle = self._call("GET", rtype, params=params).json()
        return [e["resource"] for e in bundle.get("entry", []) if e.get("search", {}).get("mode", "match") == "match"]

    def conditional_create(self, resource: dict[str, Any], identifier: str) -> dict[str, Any]:
        r = self._call("POST", resource["resourceType"], json=resource,
                       headers={"Content-Type": "application/fhir+json", "If-None-Exist": f"identifier={identifier}",
                                "Prefer": "return=representation"})
        return r.json()

    def update(self, resource: dict[str, Any]) -> dict[str, Any]:
        r = self._call("PUT", f"{resource['resourceType']}/{resource['id']}", json=resource,
                       headers={"Content-Type": "application/fhir+json", "Prefer": "return=representation"})
        return r.json()


# ---------- mapping ----------

def vitals_observation(patient_id: str, visit_id: str, values: dict[str, Any], key: str,
                       when: datetime | None = None) -> dict[str, Any]:
    components = []
    for name, value in values.items():
        if value is None or name not in COMPONENTS:
            continue
        system, code, unit = COMPONENTS[name]
        comp: dict[str, Any] = {"code": {"coding": [{"system": system, "code": code}]}}
        if unit is None:
            comp["valueCodeableConcept"] = {"coding": [{"system": AFYA, "code": str(value).lower()}]}
        else:
            comp["valueQuantity"] = {"value": float(value), "unit": unit,
                                     "system": "http://unitsofmeasure.org", "code": unit}
        components.append(comp)
    return {
        "resourceType": "Observation",
        "status": "final",
        "identifier": [{"system": REQ_SYSTEM, "value": key}],
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                  "code": "vital-signs"}]}],
        "code": {"coding": [{"system": LOINC, "code": "85353-1"}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{visit_id}"},
        "effectiveDateTime": (when or datetime.now(timezone.utc)).isoformat(),
        "component": components,
    }


def observation_values(obs: dict[str, Any]) -> dict[str, Any]:
    """Back from FHIR to {"resp_rate": 26.0, "mobility": "walking", ...}. Unknown components are ignored."""
    values: dict[str, Any] = {}
    for comp in obs.get("component", []):
        code = comp["code"]["coding"][0]["code"]
        name = _BY_CODE.get(code)
        if not name:
            continue
        if "valueQuantity" in comp:
            values[name] = comp["valueQuantity"]["value"]
        elif "valueCodeableConcept" in comp:
            values[name] = comp["valueCodeableConcept"]["coding"][0]["code"]
    return values


def age_years(patient: dict[str, Any], on: date | None = None) -> float | None:
    bd = patient.get("birthDate")
    if not bd:
        return None
    born = date.fromisoformat(bd[:10]) if len(bd) >= 10 else date(int(bd[:4]), 7, 1)
    return ((on or date.today()) - born).days / 365.25


def confirmed_colour(encounter: dict[str, Any]) -> str | None:
    for coding in encounter.get("priority", {}).get("coding", []):
        if coding.get("system") == COLOUR_SYSTEM:
            return coding["code"]
    return None


def ref_id(reference: str) -> str:
    return reference.split("/", 1)[1]
