"""Minimal FHIR R4 access for afya-mcp, plus the mapping between our vitals and FHIR Observations.

One reading = one Observation (LOINC 85353-1 vital signs panel) with one component per input.
Its business identifier (urn:afya:req|<idempotency key>) makes creation idempotent (conditional create).
The confirmed SATS colour of a visit lives on Encounter.priority (system urn:afya:sats-colour).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote

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
_BY_CODE = {(system, code): name for name, (system, code, _u) in COMPONENTS.items()}
PANEL_CODE = "85353-1"
COLOURS = ("GREEN", "YELLOW", "ORANGE", "RED")


class Fhir(Protocol):
    def read(self, rtype: str, rid: str) -> dict[str, Any]: ...
    def search(self, rtype: str, params: dict[str, str]) -> list[dict[str, Any]]: ...
    def conditional_create(self, resource: dict[str, Any], identifier: str) -> dict[str, Any]: ...
    def update(self, resource: dict[str, Any]) -> dict[str, Any]: ...


class FhirUnavailable(Exception):
    """FHIR server down or timing out (the agent retries, then warns the nurse)."""


class FhirRejected(Exception):
    """FHIR answered 4xx: the request itself is wrong (bad ID, invalid resource). Retrying will not help."""


class FhirNotFound(FhirRejected):
    """The record does not exist (404/410)."""


class HttpFhir:
    """Talks to HAPI on the internal, write-capable URL. Never handed to the model."""

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.client = httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=timeout,
                                   # HAPI reuses an identical search for 60 s unless told not to: the "newest reading"
                                   # query must see a reading saved a moment ago.
                                   headers={"Accept": "application/fhir+json", "Cache-Control": "no-cache"})

    def _call(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        try:
            r = self.client.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise FhirUnavailable(f"{method} {url}: {e}") from e
        if r.status_code >= 500 or r.status_code == 429:
            raise FhirUnavailable(f"{method} {url}: HTTP {r.status_code}")
        if r.status_code in (404, 410):
            raise FhirNotFound(f"{method} {url}: HTTP {r.status_code}")
        if r.status_code >= 400:
            raise FhirRejected(f"{method} {url}: HTTP {r.status_code}: {_diagnostics(r)}")
        try:
            return r.json()
        except ValueError as e:
            raise FhirUnavailable(f"{method} {url}: response is not JSON") from e

    def read(self, rtype: str, rid: str) -> dict[str, Any]:
        return self._call("GET", f"{rtype}/{quote(rid, safe='')}")

    def search(self, rtype: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """First page only: callers set _count to what they need."""
        bundle = self._call("GET", rtype, params=params)
        return [e["resource"] for e in bundle.get("entry", []) if e.get("search", {}).get("mode", "match") == "match"]

    def conditional_create(self, resource: dict[str, Any], identifier: str) -> dict[str, Any]:
        # If-None-Exist carries a query string: percent-encode the token so "&", "#" or spaces cannot change it.
        return self._call("POST", resource["resourceType"], json=resource,
                          headers={"Content-Type": "application/fhir+json",
                                   "If-None-Exist": f"identifier={quote(identifier, safe='|:')}",
                                   "Prefer": "return=representation"})

    def update(self, resource: dict[str, Any]) -> dict[str, Any]:
        return self._call("PUT", f"{resource['resourceType']}/{quote(resource['id'], safe='')}", json=resource,
                          headers={"Content-Type": "application/fhir+json", "Prefer": "return=representation"})


def _diagnostics(r: httpx.Response) -> str:
    """Short reason from an OperationOutcome, never the resource itself (no patient text in errors)."""
    try:
        issues = r.json().get("issue", [])
    except ValueError:
        return "no details"
    return "; ".join(str(i.get("diagnostics") or i.get("code", "")) for i in issues)[:300] or "no details"


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


class UnusableObservation(ValueError):
    """A stored reading cannot be scored as it is (wrong unit, wrong code). Nothing is guessed."""


def observation_values(obs: dict[str, Any]) -> dict[str, Any]:
    """Back from FHIR to {"resp_rate": 26.0, "mobility": "walking", ...}.

    Components are matched on system AND code; unknown ones are ignored. A quantity in another unit than the
    one the chart expects (e.g. [degF]) raises instead of being scored as if it were in the expected unit.
    """
    values: dict[str, Any] = {}
    for comp in obs.get("component", []):
        name = next((_BY_CODE[(c.get("system"), c.get("code"))] for c in comp.get("code", {}).get("coding", [])
                     if (c.get("system"), c.get("code")) in _BY_CODE), None)
        if not name:
            continue
        unit = COMPONENTS[name][2]
        if "valueQuantity" in comp:
            q = comp["valueQuantity"]
            if unit is None or q.get("code", q.get("unit")) != unit:
                raise UnusableObservation(f"{name}: unit {q.get('code', q.get('unit'))!r}, expected {unit!r}")
            if q.get("value") is not None:
                values[name] = q["value"]
        elif "valueCodeableConcept" in comp:
            codings = comp["valueCodeableConcept"].get("coding", [])
            if unit is not None or not codings:
                raise UnusableObservation(f"{name}: coded value where a quantity is expected")
            values[name] = codings[0]["code"]
    return values


def age_years(patient: dict[str, Any], on: date | None = None) -> float | None:
    """Calendar age in years (whole years + fraction of the current year). Partial dates use the middle of the
    period. Today is taken in UTC so the result does not depend on the container's time zone."""
    bd = patient.get("birthDate")
    if not bd:
        return None
    if len(bd) >= 10:
        born = date.fromisoformat(bd[:10])
    elif len(bd) == 7:
        born = date(int(bd[:4]), int(bd[5:7]), 15)
    else:
        born = date(int(bd[:4]), 7, 1)
    today = on or datetime.now(timezone.utc).date()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    last = _anniversary(born, born.year + years)
    span = (_anniversary(born, born.year + years + 1) - last).days
    return years + (today - last).days / span


def _anniversary(born: date, year: int) -> date:
    try:
        return born.replace(year=year)
    except ValueError:          # 29 February in a non-leap year
        return date(year, 3, 1)


def confirmed_colour(encounter: dict[str, Any]) -> str | None:
    """Colour a nurse last confirmed. Anything that is not a SATS colour raises rather than being guessed."""
    for coding in (encounter.get("priority") or {}).get("coding", []):
        if coding.get("system") == COLOUR_SYSTEM:
            code = str(coding.get("code", "")).upper()
            if code not in COLOURS:
                raise ValueError(f"Encounter.priority has unknown SATS colour {coding.get('code')!r}")
            return code
    return None


def ref_id(reference: str, rtype: str | None = None) -> str:
    """ID from "Patient/1", "Patient/1/_history/2", "http://host/fhir/Patient/1" or a bare "1".
    With rtype, a reference to another resource type raises."""
    parts = [p for p in reference.split("/") if p]
    if "_history" in parts:
        parts = parts[: parts.index("_history")]
    if not parts:
        raise ValueError("empty reference")
    if len(parts) >= 2 and rtype is not None and parts[-2] != rtype:
        raise ValueError(f"expected a {rtype} reference, got {reference!r}")
    return parts[-1]
