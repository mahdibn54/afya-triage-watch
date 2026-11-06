"""Tool logic for afya-mcp, independent of the MCP transport so it can be unit-tested with a fake FHIR store.

The MCP tools in server.py are thin wrappers around these functions.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from . import rules
from .db import VisitStore
from .fhir import (
    COMPONENTS,
    PANEL_CODE,
    REQ_SYSTEM,
    Fhir,
    FhirNotFound,
    UnusableObservation,
    age_years,
    confirmed_colour,
    observation_values,
    ref_id,
    vitals_observation,
)

KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
USABLE_STATUSES = ("final", "amended", "corrected")
WAITING_STATUSES = ("arrived", "triaged", "in-progress")
QUEUE_LIMIT = 100


def record_vitals(fhir: Fhir, plausibility: dict[str, Any], registry: list[dict[str, Any]], patient_id: str,
                  visit_id: str, values: dict[str, Any], idempotency_key: str,
                  when: datetime | None = None, store: VisitStore | None = None) -> dict[str, Any]:
    """E4-2. Validation and plausibility first: anything wrong or impossible means nothing is saved.

    Conditional create on the request identifier, so a retried call returns the same Observation.
    After the FHIR write, the visit row and latest_obs_id are upserted in Postgres (`store`, one transaction). The
    latest reading is read back from FHIR, so a retry of an older entry never moves latest_obs_id backwards. If the
    database write fails the error propagates; the nurse's retry converges (same Observation, same upsert).
    """
    problems = _invalid_entry(values, registry, idempotency_key)
    if problems:
        return {"status": "invalid", "saved": False, "problems": problems}
    implausible = rules.check_plausible(values, plausibility)
    if implausible:
        return {"status": "remeasure", "saved": False, "problems": [asdict(p) for p in implausible]}
    pid, vid = ref_id(patient_id, "Patient"), ref_id(visit_id, "Encounter")
    encounter = fhir.read("Encounter", vid)
    if encounter.get("subject", {}).get("reference", "").rstrip("/").split("/")[-2:] != ["Patient", pid]:
        return {"status": "invalid", "saved": False, "problems": ["visit does not belong to this patient"]}
    obs = vitals_observation(pid, vid, values, idempotency_key, when)
    created = fhir.conditional_create(obs, f"{REQ_SYSTEM}|{idempotency_key}")
    if store is not None:
        newest = fhir.search("Observation", {"encounter": f"Encounter/{vid}", "code": f"http://loinc.org|{PANEL_CODE}",
                                             "status": ",".join(USABLE_STATUSES), "_sort": "-date", "_count": "1"})
        store.record_reading(vid, pid, newest[0]["id"] if newest else created["id"])
    return {"status": "saved", "saved": True, "observation_id": f"Observation/{created['id']}"}


def _invalid_entry(values: dict[str, Any], registry: list[dict[str, Any]], key: str) -> list[str]:
    """Reject what would otherwise be silently dropped or only fail later at scoring time."""
    problems: list[str] = []
    if not KEY_PATTERN.match(key or ""):
        problems.append("idempotency_key must be 1-64 characters: letters, digits, . _ : -")
    present = {k: v for k, v in values.items() if v is not None}
    if not present:
        problems.append("no values")
    categorical: dict[str, set[str]] = {}
    for chart in registry:
        for name, spec in chart["categorical"].items():
            categorical.setdefault(name, set()).update(spec["values"])
    for name, value in present.items():
        if name not in COMPONENTS:
            problems.append(f"unknown input {name!r}")
        elif name in categorical:
            if str(value).lower() not in categorical[name]:
                problems.append(f"{name}: {value!r} is not one of {sorted(categorical[name])}")
        elif isinstance(value, bool) or not isinstance(value, (int, float, str)):
            problems.append(f"{name}: not a number")
        else:
            try:
                number = float(value)
            except ValueError:
                problems.append(f"{name}: not a number")
            else:
                if number != number or number in (float("inf"), float("-inf")):
                    problems.append(f"{name}: not a number")
    return problems


def compute_tews(fhir: Fhir, registry: list[dict[str, Any]], observation_id: str) -> dict[str, Any]:
    """E4-3. Takes only a record ID and reads the values itself, so the model can never mistype a vital sign."""
    oid = ref_id(observation_id, "Observation")
    ref = f"Observation/{oid}"
    obs = fhir.read("Observation", oid)
    codes = {c.get("code") for c in obs.get("code", {}).get("coding", [])}
    if PANEL_CODE not in codes or obs.get("status") not in USABLE_STATUSES:
        return {"status": "not_usable", "observation_id": ref,
                "notice": "not a current vital-signs reading (wrong code or status)"}
    patient = fhir.read("Patient", ref_id(obs["subject"]["reference"], "Patient"))
    try:
        chart = rules.select_chart(age_years(patient), _height_cm(patient), registry)
    except rules.NoChartForPatient as e:
        return {"status": "no_chart", "observation_id": ref, "notice": str(e)}
    try:
        values = observation_values(obs)
        s = rules.score(values, chart, {name: ref for name in values})
    except (UnusableObservation, ValueError) as e:
        return {"status": "not_usable", "observation_id": ref, "notice": f"cannot score this reading: {e}"}
    return {"status": "scored", "observation_id": ref, "effective": obs.get("effectiveDateTime"), **asdict(s)}


def check_deterioration(fhir: Fhir, registry: list[dict[str, Any]], visit_id: str) -> dict[str, Any]:
    """E4-4. Latest reading vs the colour a nurse last confirmed (Encounter.priority), plus the previous reading.

    If no colour was confirmed yet, the previous reading is the reference (only the very first reading is a
    baseline). Returns the code-decided trigger without warning signs; the agent re-evaluates with validated signs.
    """
    vid = ref_id(visit_id, "Encounter")
    encounter = fhir.read("Encounter", vid)
    readings = fhir.search("Observation", {"encounter": f"Encounter/{vid}", "code": f"http://loinc.org|{PANEL_CODE}",
                                           "status": ",".join(USABLE_STATUSES), "_sort": "-date", "_count": "2"})
    if not readings:
        return {"status": "no_readings", "visit_id": vid}
    latest = compute_tews(fhir, registry, readings[0]["id"])
    if latest["status"] != "scored":
        return {"status": latest["status"], "visit_id": vid, "latest": latest}
    previous = compute_tews(fhir, registry, readings[1]["id"]) if len(readings) > 1 else None
    if previous is not None and previous["status"] != "scored":
        previous = None
    confirmed = confirmed_colour(encounter)
    chart = next(c for c in registry if c["chart_id"] == latest["chart_id"])
    after = rules.Score(**{k: latest[k] for k in rules.Score.__dataclass_fields__})
    trigger = rules.evaluate_trigger(confirmed, after, [], chart,
                                     previous_colour=previous["colour"] if previous else None)
    return {
        "status": "checked",
        "visit_id": vid,
        "confirmed_colour": confirmed,
        "latest": {k: latest[k] for k in ("observation_id", "effective", "tews", "colour", "complete", "missing",
                                          "signs")},
        "previous": {k: previous[k] for k in ("observation_id", "effective", "tews", "colour")} if previous else None,
        "changes": _changes(previous, latest) if previous else [],
        "trigger": {"kind": trigger.kind, "from": trigger.from_colour, "to": trigger.to_colour,
                    "reasons": trigger.reasons, "propose": trigger.propose},
    }


def _changes(previous: dict[str, Any], latest: dict[str, Any]) -> list[dict[str, Any]]:
    """Per input: points before and after, with the record behind each, for the evidence table on the card.
    Inputs present in only one of the two readings are listed too (points None on the missing side)."""
    out = []
    for name in [*latest["points"], *(n for n in previous["points"] if n not in latest["points"])]:
        before, after = previous["points"].get(name), latest["points"].get(name)
        if before != after:
            out.append({"input": name, "points_before": before, "points_after": after,
                        "before": previous["cited"].get(name), "after": latest["cited"].get(name)})
    return out


def _height_cm(patient: dict[str, Any]) -> float | None:
    for ext in patient.get("extension", []):
        if ext.get("url") == "urn:afya:height-cm" and ext.get("valueDecimal") is not None:
            return float(ext["valueDecimal"])
    return None


# ---------- E4-5: queue state ----------

def get_queue_state(fhir: Fhir, registry: list[dict[str, Any]], site: dict[str, Any],
                    store: VisitStore | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Read-only. For each waiting visit (FHIR Encounter in arrived/triaged/in-progress), oldest arrival first:
    minutes waited since Encounter.period.start against the SATS target of the colour a nurse confirmed
    (Encounter.priority; target from the patient's chart), and when the next reading is due by the site re-check
    interval (site rule, not SATS). Plus the proposals nobody has decided (pending) or reviewed (superseded), with
    their age, from Postgres. Only IDs, codes, times and numbers: no names or notes.
    """
    now = now or datetime.now(timezone.utc)
    encounters = fhir.search("Encounter", {"status": ",".join(WAITING_STATUSES), "_sort": "-date",
                                           "_count": str(QUEUE_LIMIT)})
    proposals = _open_proposals(store, site, now)
    pending_by_visit: dict[str, int] = {}
    for p in proposals or []:
        if p["status"] == "pending":
            pending_by_visit[p["visit_id"]] = pending_by_visit.get(p["visit_id"], 0) + 1
    charts: dict[str, dict[str, Any] | None] = {}
    patients = [_queue_entry(fhir, registry, site, e, charts, pending_by_visit, now) for e in encounters]
    patients.sort(key=lambda p: (p["arrived_at"] is None, p["arrived_at"] or ""))
    return {
        "status": "ok",
        "as_of": now.isoformat(),
        "site_rule_source": site.get("source"),
        "truncated": len(encounters) >= QUEUE_LIMIT,
        "patients": patients,
        "proposals": proposals,
        "notices": [] if proposals is not None else ["proposals unavailable: no database connection"],
    }


def _queue_entry(fhir: Fhir, registry: list[dict[str, Any]], site: dict[str, Any], enc: dict[str, Any],
                 charts: dict[str, dict[str, Any] | None], pending_by_visit: dict[str, int],
                 now: datetime) -> dict[str, Any]:
    vid = enc["id"]
    notices: list[str] = []
    pid = None
    try:
        pid = ref_id(enc.get("subject", {}).get("reference", ""), "Patient")
    except ValueError:
        notices.append("visit has no patient reference")
    try:
        colour = confirmed_colour(enc)
    except ValueError:
        colour = None
        notices.append("Encounter.priority holds an unknown colour")
    arrived = _when(enc.get("period", {}).get("start"))
    if arrived is None:
        notices.append("arrival time unknown (Encounter.period.start)")
    waited = _minutes(now - arrived) if arrived else None

    target = None
    if colour and pid:
        chart = _chart_for(fhir, registry, pid, charts)
        if chart is None:
            notices.append("no chart for this patient yet: no SATS target")
        else:
            target = rules.target_minutes(chart, colour)
    over = max(0, waited - target) if waited is not None and target is not None else None

    latest = fhir.search("Observation", {"encounter": f"Encounter/{vid}", "code": f"http://loinc.org|{PANEL_CODE}",
                                         "status": ",".join(USABLE_STATUSES), "_sort": "-date", "_count": "1"})
    last = {"observation_id": f"Observation/{latest[0]['id']}",
            "effective": latest[0].get("effectiveDateTime")} if latest else None
    return {
        "visit_id": vid,
        "patient_id": pid,
        "confirmed_colour": colour,
        "arrived_at": arrived.isoformat() if arrived else None,
        "minutes_waited": waited,
        "target_minutes": target,
        "over_target_minutes": over,
        "over_target": bool(over),
        "last_reading": last,
        "recheck": _recheck(site, colour, arrived, _when(last["effective"]) if last else None, last is None, now),
        "pending_proposals": pending_by_visit.get(vid, 0),
        "notices": notices,
    }


def _recheck(site: dict[str, Any], colour: str | None, arrived: datetime | None, last_at: datetime | None,
             no_reading: bool, now: datetime) -> dict[str, Any]:
    """Next reading due = last reading (or arrival) + the site interval for the confirmed colour.
    Without a confirmed colour only the first reading is due (on arrival); no interval is guessed."""
    interval = site.get("recheck_minutes", {}).get(colour) if colour else None
    if interval is not None and (last_at or arrived):
        due = (last_at or arrived) + timedelta(minutes=interval)
    elif no_reading and arrived:
        due = arrived
    else:
        due = None
    overdue = due is not None and now >= due
    return {"rule": "site rule", "interval_minutes": interval, "due_at": due.isoformat() if due else None,
            "overdue": overdue, "overdue_minutes": _minutes(now - due) if overdue else 0 if due else None}


def _open_proposals(store: VisitStore | None, site: dict[str, Any], now: datetime) -> list[dict[str, Any]] | None:
    if store is None:
        return None
    remind = site.get("clinician_reminder_after_minutes", {})
    out = []
    for p in store.open_proposals():
        age = _minutes(now - p["created_at"])
        limit = remind.get(p["to_colour"])
        out.append({"proposal_id": str(p["id"]), "visit_id": p["visit_id"], "status": p["status"],
                    "trigger": p["trigger"], "to_colour": p["to_colour"], "obs_id": p["obs_id"],
                    "created_at": p["created_at"].isoformat(), "age_minutes": age,
                    "reminder_due": p["status"] == "pending" and limit is not None and age >= limit})
    return out


def _chart_for(fhir: Fhir, registry: list[dict[str, Any]], pid: str,
               cache: dict[str, dict[str, Any] | None]) -> dict[str, Any] | None:
    if pid not in cache:
        try:
            patient = fhir.read("Patient", pid)
            cache[pid] = rules.select_chart(age_years(patient), _height_cm(patient), registry)
        except (FhirNotFound, rules.NoChartForPatient):
            cache[pid] = None
    return cache[pid]


def _when(value: str | None) -> datetime | None:
    """FHIR dateTime to an aware datetime (no zone means UTC). Unparseable means unknown, never guessed."""
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)

