"""Tool logic for afya-mcp, independent of the MCP transport so it can be unit-tested with a fake FHIR store.

The MCP tools in server.py are thin wrappers around these functions.
"""
from __future__ import annotations

import contextlib
import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from . import rules, workflow
from .db import VisitStore
from .fhir import (
    AFYA,
    COLOUR_SYSTEM,
    COLOURS,
    COMPONENTS,
    PANEL_CODE,
    REQ_SYSTEM,
    Fhir,
    FhirNotFound,
    FhirUnavailable,
    UnusableObservation,
    age_years,
    confirmed_colour,
    observation_values,
    ref_id,
    vitals_observation,
)

LABEL_SYSTEM = "urn:afya:label"
MAX_COMPLAINT = 500
KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
USABLE_STATUSES = ("final", "amended", "corrected")
WAITING_STATUSES = ("arrived", "triaged", "in-progress")
QUEUE_LIMIT = 100


def record_vitals(fhir: Fhir, plausibility: dict[str, Any], registry: list[dict[str, Any]], patient_id: str | None,
                  visit_id: str, values: dict[str, Any], idempotency_key: str,
                  when: datetime | None = None, store: VisitStore | None = None,
                  complaint: str | None = None, reported_worsening: bool = False) -> dict[str, Any]:
    """E4-2. Validation and plausibility first: anything wrong or impossible means nothing is saved.

    Conditional create on the request identifier, so a retried call returns the same Observation.
    patient_id may be None: the patient is then the visit's subject. complaint: free text (Postgres only, see
    _clean_complaint). After the FHIR write, the visit row and latest_obs_id are upserted in Postgres (`store`, one
    transaction). The latest reading is read back from FHIR, so a retry of an older entry never moves latest_obs_id
    backwards. If the database write fails the error propagates; the nurse's retry converges (same Observation,
    same upsert).
    """
    problems = _invalid_entry(values, registry, idempotency_key)
    clean_complaint, complaint_problem = _clean_complaint(complaint)
    problems += complaint_problem
    if not isinstance(reported_worsening, bool):
        problems.append("reported_worsening: not true or false")
    if problems:
        return {"status": "invalid", "saved": False, "problems": problems}
    implausible = rules.check_plausible(values, plausibility)
    if implausible:
        return {"status": "remeasure", "saved": False, "problems": [asdict(p) for p in implausible]}
    vid = ref_id(visit_id, "Encounter")
    encounter = fhir.read("Encounter", vid)
    subject = encounter.get("subject", {}).get("reference", "").rstrip("/").split("/")[-2:]
    pid = ref_id(patient_id, "Patient") if patient_id else (subject[-1] if subject[:1] == ["Patient"] else "")
    if not pid or subject != ["Patient", pid]:
        return {"status": "invalid", "saved": False, "problems": ["visit does not belong to this patient"]}
    obs = vitals_observation(pid, vid, values, idempotency_key, when)
    created = fhir.conditional_create(obs, f"{REQ_SYSTEM}|{idempotency_key}")
    if store is not None:
        newest = fhir.search("Observation", {"encounter": f"Encounter/{vid}", "code": f"http://loinc.org|{PANEL_CODE}",
                                             "status": ",".join(USABLE_STATUSES), "_sort": "-date", "_count": "1"})
        store.record_reading(vid, pid, newest[0]["id"] if newest else created["id"], _patient_label(fhir, pid))
        # api.md Q1: Postgres only, never FHIR; a retry keeps the first row
        if clean_complaint or reported_worsening:
            store.save_complaint(vid, created["id"], clean_complaint, reported_worsening)
    return {"status": "saved", "saved": True, "observation_id": f"Observation/{created['id']}"}


def _clean_complaint(text: str | None) -> tuple[str | None, list[str]]:
    """NFKC-normalised, control characters turned into spaces, trimmed; empty means none. At most 500 characters
    AFTER normalisation (architecture Appendix B), so what is stored is what the limit was checked on."""
    if text is None:
        return None, []
    if not isinstance(text, str):
        return None, ["complaint: not text"]
    clean = "".join(c if c == "\n" or c.isprintable() else " " for c in unicodedata.normalize("NFKC", text)).strip()
    if len(clean) > MAX_COMPLAINT:
        return None, [f"complaint: at most {MAX_COMPLAINT} characters"]
    return clean or None, []


def _patient_label(fhir: Fhir, patient_id: str) -> str | None:
    """Display label (Patient.identifier urn:afya:label), or None. Never a name."""
    try:
        return label_of(fhir.read("Patient", patient_id))
    except FhirNotFound:
        return None


def label_of(patient: dict[str, Any]) -> str | None:
    return next((i["value"] for i in patient.get("identifier", []) if i.get("system") == LABEL_SYSTEM
                 and i.get("value")), None)


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
    return _score_reading(obs, patient, registry)


def _score_reading(obs: dict[str, Any], patient: dict[str, Any], registry: list[dict[str, Any]]) -> dict[str, Any]:
    """Score an already-read usable Observation for its (already-read) Patient."""
    ref = f"Observation/{obs['id']}"
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
    patient_label, minutes waited since Encounter.period.start against the SATS target of the colour a nurse
    confirmed (Encounter.priority; target from the patient's chart), the last reading with its TEWS and colour, active
    flags, and when the next reading is due by the site re-check interval (site rule, not SATS). Plus the proposals
    nobody has decided (pending) or reviewed (superseded), with their age, from Postgres. Only IDs, codes, times and
    numbers: no names or notes. Notices are objects {code, notification_id?, at?} with the codes of docs/api.md
    section 6; if FHIR cannot be reached the patients are empty and the notice is fhir_unavailable (not an error).
    """
    now = now or datetime.now(timezone.utc)
    proposals = _open_proposals(store, site, now)
    notifications = store.open_notifications() if store is not None else []
    notices: list[dict[str, Any]] = [] if store is not None else [{"code": "data_incomplete"}]
    notices += [workflow.notice_from_notification(n) for n in notifications if not n["visit_id"]]
    pending_by_visit: dict[str, int] = {}
    unreviewed = set()
    for p in proposals or []:
        if p["status"] == "pending":
            pending_by_visit[p["visit_id"]] = pending_by_visit.get(p["visit_id"], 0) + 1
        else:
            unreviewed.add(p["visit_id"])
    by_visit: dict[str, list[dict[str, Any]]] = {}
    for n in notifications:
        if n["visit_id"]:
            by_visit.setdefault(n["visit_id"], []).append(workflow.notice_from_notification(n))
    patients: list[dict[str, Any]] = []
    truncated = False
    try:
        encounters = fhir.search("Encounter", {"status": ",".join(WAITING_STATUSES), "_sort": "-date",
                                               "_count": str(QUEUE_LIMIT)})
        truncated = len(encounters) >= QUEUE_LIMIT
        cache: dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]] = {}
        patients = [_queue_entry(fhir, registry, site, e, cache, pending_by_visit, unreviewed,
                                 by_visit.get(e["id"], []), now) for e in encounters]
    except FhirUnavailable:
        patients = []
        notices.append({"code": "fhir_unavailable"})
    patients.sort(key=lambda p: (p["arrived_at"] is None, p["arrived_at"] or ""))
    return {
        "status": "ok",
        "as_of": now.isoformat(),
        "site_rule_source": site.get("source"),
        "truncated": truncated,
        "patients": patients,
        "proposals": proposals,
        "notices": notices,
    }


def _queue_entry(fhir: Fhir, registry: list[dict[str, Any]], site: dict[str, Any], enc: dict[str, Any],
                 cache: dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]],
                 pending_by_visit: dict[str, int], unreviewed: set[str], visit_notices: list[dict[str, Any]],
                 now: datetime) -> dict[str, Any]:
    vid = enc["id"]
    notices: list[dict[str, Any]] = []
    pid = None
    try:
        pid = ref_id(enc.get("subject", {}).get("reference", ""), "Patient")
    except ValueError:
        notices.append({"code": "data_incomplete"})
    try:
        colour = confirmed_colour(enc)
    except ValueError:
        colour = None
        notices.append({"code": "data_incomplete"})
    arrived = _when(enc.get("period", {}).get("start"))
    if arrived is None:
        notices.append({"code": "data_incomplete"})
    waited = _minutes(now - arrived) if arrived else None

    patient, chart = _patient_and_chart(fhir, registry, pid, cache) if pid else (None, None)
    target = None
    if colour and pid:
        if chart is None:
            notices.append({"code": "no_chart"})
        else:
            target = rules.target_minutes(chart, colour)
    over = max(0, waited - target) if waited is not None and target is not None else None

    latest = fhir.search("Observation", {"encounter": f"Encounter/{vid}", "code": f"http://loinc.org|{PANEL_CODE}",
                                         "status": ",".join(USABLE_STATUSES), "_sort": "-date", "_count": "1"})
    last = None
    if latest:
        scored = _score_reading(latest[0], patient, registry) if patient is not None else {}
        last = {"observation_id": f"Observation/{latest[0]['id']}", "effective": latest[0].get("effectiveDateTime"),
                "tews": scored.get("tews"), "colour": scored.get("colour")}
    # HAPI has no status search parameter on Flag: filter in code
    flags = fhir.search("Flag", {"encounter": f"Encounter/{vid}", "_count": "50"})
    if any(_is_second_look(f) for f in flags):
        flag_codes = ["second_look"]
    else:
        flag_codes = []
    if vid in unreviewed:
        notices.append({"code": "not_reviewed"})
    return {
        "visit_id": vid,
        "patient_id": pid,
        "patient_label": label_of(patient) if patient else None,
        "confirmed_colour": colour,
        "arrived_at": arrived.isoformat() if arrived else None,
        "minutes_waited": waited,
        "target_minutes": target,
        "over_target_minutes": over,
        "over_target": bool(over),
        "last_reading": last,
        "recheck": _recheck(site, colour, arrived, _when(last["effective"]) if last else None, last is None, now),
        "pending_proposals": pending_by_visit.get(vid, 0),
        "flags": flag_codes,
        "notices": [*_dedup(notices), *visit_notices],
    }


def _dedup(notices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [n for i, n in enumerate(notices) if n not in notices[:i]]


def _is_second_look(flag: dict[str, Any]) -> bool:
    return flag.get("status") == "active" and any(
        c.get("code") == "second-look" for c in flag.get("code", {}).get("coding", []))


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


def _patient_and_chart(fhir: Fhir, registry: list[dict[str, Any]], pid: str,
                       cache: dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]]
                       ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The Patient (None if it does not exist) and the chart that fits it (None if there is none yet)."""
    if pid not in cache:
        try:
            patient = fhir.read("Patient", pid)
        except FhirNotFound:
            cache[pid] = (None, None)
        else:
            try:
                cache[pid] = (patient, rules.select_chart(age_years(patient), _height_cm(patient), registry))
            except rules.NoChartForPatient:
                cache[pid] = (patient, None)
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


# ---------- E6-5: visit timeline (read by the api, never offered to the model) ----------

def visit_timeline(fhir: Fhir, registry: list[dict[str, Any]], visit_id: str) -> dict[str, Any]:
    """Readings of one visit, oldest first, with the raw values from FHIR (api.md Q5) and the points of each input.
    points is None for an input that is shown but not scored (SpO2). Only IDs, codes and numbers."""
    vid = ref_id(visit_id, "Encounter")
    try:
        encounter = fhir.read("Encounter", vid)
    except FhirNotFound:
        return {"status": "not_found", "visit_id": vid}
    patient = None
    with contextlib.suppress(ValueError, FhirNotFound):
        patient = fhir.read("Patient", ref_id(encounter["subject"]["reference"], "Patient"))
    found = fhir.search("Observation", {"encounter": f"Encounter/{vid}", "code": f"http://loinc.org|{PANEL_CODE}",
                                        "status": ",".join(USABLE_STATUSES), "_sort": "-date", "_count": "100"})
    readings, chart_id = [], None
    for obs in sorted(found, key=lambda o: o.get("effectiveDateTime", "")):
        scored = _score_reading(obs, patient, registry) if patient is not None else {}
        try:
            values = observation_values(obs)
        except UnusableObservation:
            values = {}
        points = scored.get("points", {}) if scored.get("status") == "scored" else {}
        chart_id = chart_id or scored.get("chart_id")
        readings.append({
            "obs_id": f"Observation/{obs['id']}",
            "at": obs.get("effectiveDateTime"),
            "values": {name: {"value": _plain(values[name]), "unit": COMPONENTS[name][2], "points": points.get(name)}
                       for name in COMPONENTS if name in values},
            "tews": scored.get("tews"), "colour": scored.get("colour"), "complete": scored.get("complete", False),
            "missing": scored.get("missing", []), "signs": scored.get("signs", []),
        })
    return {"status": "ok", "visit_id": vid, "chart_id": chart_id, "readings": readings}


def _plain(v: Any) -> Any:
    return int(v) if isinstance(v, float) and v.is_integer() else v


# ---------- E6-6: demo visit (synthetic data only, DEMO_MODE) ----------

DEMO_SYSTEM = "urn:afya:demo"


def seed_demo_visit(fhir: Fhir, label: str, birth_date: str, arrived_minutes_ago: int, confirmed_colour: str | None,
                    now: datetime | None = None) -> dict[str, Any]:
    """Create (or reuse) the synthetic Patient and a fresh in-progress Encounter.

    `confirmed_colour` is the nurse's existing confirmation; None leaves the first visit unconfirmed. Earlier waiting
    Encounters of this demo patient are finished so reloading starts a clean entry. Synthetic labels only, no names.
    """
    if not re.fullmatch(r"[A-Za-z0-9-]{1,32}", label or ""):
        return {"status": "invalid", "reason": "label must be 1-32 letters, digits or '-'"}
    if confirmed_colour is not None and confirmed_colour not in COLOURS:
        return {"status": "invalid", "reason": f"confirmed_colour must be one of {COLOURS}, or null"}
    now = now or datetime.now(timezone.utc)
    patient = fhir.conditional_create(
        {"resourceType": "Patient", "identifier": [{"system": LABEL_SYSTEM, "value": label}], "birthDate": birth_date,
         "gender": "other"}, f"{LABEL_SYSTEM}|{label}")
    for old in fhir.search("Encounter", {"subject": f"Patient/{patient['id']}", "status": ",".join(WAITING_STATUSES)}):
        fhir.update({**old, "status": "finished"})
    key = uuid.uuid4().hex
    encounter = {"resourceType": "Encounter", "status": "in-progress", "class": {"code": "EMER"},
                 "identifier": [{"system": DEMO_SYSTEM, "value": key}],
                 "subject": {"reference": f"Patient/{patient['id']}"},
                 "period": {"start": (now - timedelta(minutes=arrived_minutes_ago)).isoformat()}}
    if confirmed_colour is not None:
        encounter["priority"] = {"coding": [{"system": COLOUR_SYSTEM, "code": confirmed_colour}]}
    enc = fhir.conditional_create(encounter, f"{DEMO_SYSTEM}|{key}")
    return {"status": "seeded", "patient_id": patient["id"], "visit_id": enc["id"], "patient_label": label}


def demo_visit(fhir: Fhir, label: str) -> dict[str, Any]:
    """The waiting Encounter of the demo patient with this label and how many readings it has so far."""
    patients = fhir.search("Patient", {"identifier": f"{LABEL_SYSTEM}|{label}", "_count": "1"})
    if not patients:
        return {"status": "not_found"}
    pid = patients[0]["id"]
    encounters = fhir.search("Encounter", {"subject": f"Patient/{pid}", "status": ",".join(WAITING_STATUSES),
                                           "_count": "1"})
    if not encounters:
        return {"status": "not_found"}
    vid = encounters[0]["id"]
    n = len(fhir.search("Observation", {"encounter": f"Encounter/{vid}", "code": f"http://loinc.org|{PANEL_CODE}",
                                        "status": ",".join(USABLE_STATUSES), "_count": "100"}))
    return {"status": "found", "visit_id": vid, "patient_id": pid, "readings": n}


# ---------- E4-6: executor registry and raise_recheck_flag ----------

COMMAND_SYSTEM = "urn:afya:command"
EVIDENCE_URL = "urn:afya:evidence"
FHIR_ID = re.compile(r"^[A-Za-z0-9.-]{1,64}$")


def raise_recheck_flag(fhir: Fhir, conn: psycopg.Connection, command_id: str, actor: str,
                       run_id: str | None = None) -> dict[str, Any]:
    """E4-6. Execute a nurse-approved command (input: its ID only). Order of writes (architecture s. 9): the intent is
    already committed in Postgres (approve) -> claim, or resume a claimed command after a crash -> idempotent FHIR
    writes through the executor registered for commands.action_type -> mark done + audit (one transaction).

    Safe on retry: the Flag is a conditional create on urn:afya:command|<command_id> and the priority is an absolute
    set, so a retry after a failure between the FHIR write and mark_done converges to the same Flag. A session
    advisory lock on the command keeps two executors from running it at the same time (released on disconnect).
    The actor must be the user who approved the proposal, or 'agent'/'system' (startup sweep, retries).
    """
    try:
        cid = str(uuid.UUID(str(command_id)))
    except ValueError:
        return {"status": "invalid", "command_id": command_id, "reason": "command_id is not a UUID"}
    if not conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS ok", (cid,)).fetchone()["ok"]:
        return {"status": "in_progress", "command_id": cid, "reason": "another executor is running this command"}
    try:
        return _execute(fhir, conn, cid, actor, run_id)
    finally:
        with contextlib.suppress(psycopg.Error):   # a broken connection releases the lock when it closes
            conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (cid,))


def _execute(fhir: Fhir, conn: psycopg.Connection, cid: str, actor: str, run_id: str | None) -> dict[str, Any]:
    row = conn.execute("SELECT c.*, p.decided_by, p.payload FROM commands c JOIN proposals p ON p.id = c.proposal_id "
                       "WHERE c.id = %s", (cid,)).fetchone()
    if row is None:
        return {"status": "not_found", "command_id": cid}
    base = {"command_id": cid, "visit_id": row["visit_id"], "action_type": row["action_type"]}
    if actor != row["decided_by"]:
        role = conn.execute("SELECT role FROM users WHERE id = %s", (actor,)).fetchone()
        if role is None or role["role"] not in ("agent", "system"):
            return {**base, "status": "refused", "reason": "actor is not the user who approved this command"}
    executor = EXECUTORS.get(row["action_type"])
    if executor is None:
        return {**base, "status": "refused", "reason": f"no executor for action_type {row['action_type']!r}"}
    if row["done_at"] is not None:
        return {**base, "status": "already_done", **executor(fhir, row, lookup_only=True)}
    command = workflow.claim_command(conn, cid) or workflow.resume_command(conn, cid)
    if command is None:
        return {**base, "status": "refused", "reason": _why_not_claimable(conn, cid)}
    written = executor(fhir, {**command, "payload": row["payload"]})
    if workflow.mark_done(conn, cid, actor, run_id) is None:
        return {**base, "status": "already_done", **written}
    return {**base, "status": "done", "attempts": command["attempts"], **written}


def _why_not_claimable(conn: psycopg.Connection, cid: str) -> str:
    r = conn.execute(
        "SELECT c.claimed_at IS NOT NULL AS claimed, c.expires_at <= now() AS expired, c.attempts, p.status, "
        "v.latest_obs_id IS DISTINCT FROM c.obs_id AS stale FROM commands c JOIN proposals p ON p.id = c.proposal_id "
        "JOIN visits v ON v.id = c.visit_id WHERE c.id = %s", (cid,)).fetchone()
    if r["status"] != "approved":
        return f"proposal is {r['status']}"
    if r["claimed"]:
        return f"stopped after {r['attempts']} attempts" if r["attempts"] >= workflow.MAX_ATTEMPTS else "not resumable"
    if r["expired"]:
        return "approval expired: the proposal must be confirmed again"
    if r["stale"]:
        return "newer vitals arrived after the approval: the new reading gets its own proposal"
    return "not claimable"


def write_recheck_flag(fhir: Fhir, command: dict[str, Any], lookup_only: bool = False) -> dict[str, Any]:
    """Executor for action_type 'recheck_flag': FHIR Flag "second look" citing the readings, and the confirmed
    colour on Encounter.priority. Both writes are idempotent. lookup_only: find the Flag of a done command."""
    cid = str(command["id"])
    if lookup_only:
        found = fhir.search("Flag", {"identifier": f"{COMMAND_SYSTEM}|{cid}", "_count": "1"})
        return {"flag_id": f"Flag/{found[0]['id']}" if found else None, "colour": command["colour"]}
    vid = ref_id(command["visit_id"], "Encounter")
    encounter = fhir.read("Encounter", vid)
    pid = ref_id(encounter["subject"]["reference"], "Patient")
    evidence = _evidence_ids(command)
    flag = {
        "resourceType": "Flag",
        "identifier": [{"system": COMMAND_SYSTEM, "value": cid}],
        "status": "active",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/flag-category",
                                  "code": "clinical"}]}],
        "code": {"coding": [{"system": AFYA, "code": "second-look", "display": "Second look requested"}]},
        "subject": {"reference": f"Patient/{pid}"},
        "encounter": {"reference": f"Encounter/{vid}"},
        "period": {"start": command["claimed_at"].isoformat()},
        "extension": [{"url": EVIDENCE_URL, "valueReference": {"reference": f"Observation/{o}"}} for o in evidence]
                     + [{"url": COLOUR_SYSTEM, "valueCode": command["colour"]}],
    }
    created = fhir.conditional_create(flag, f"{COMMAND_SYSTEM}|{cid}")
    changed = _set_priority(fhir, encounter, command["colour"])
    return {"flag_id": f"Flag/{created['id']}", "colour": command["colour"], "priority_changed": changed,
            "evidence": [f"Observation/{o}" for o in evidence]}


def _evidence_ids(command: dict[str, Any]) -> list[str]:
    """The command's reading first, then the proposal's cited readings (payload "cited_obs_ids"), IDs only."""
    out: list[str] = []
    for ref in [command["obs_id"], *(command.get("payload") or {}).get("cited_obs_ids", [])]:
        oid = ref_id(str(ref), "Observation")
        if not FHIR_ID.match(oid):
            raise ValueError(f"not an Observation id: {ref!r}")
        if oid not in out:
            out.append(oid)
    return out


def _set_priority(fhir: Fhir, encounter: dict[str, Any], colour: str) -> bool:
    """Absolute set of the confirmed colour (other priority codings kept). No write if it is already set."""
    try:
        if confirmed_colour(encounter) == colour:
            return False
    except ValueError:
        pass   # an unknown colour is overwritten by the confirmed one
    priority = encounter.get("priority") or {}
    others = [c for c in priority.get("coding", []) if c.get("system") != COLOUR_SYSTEM]
    encounter["priority"] = {**priority, "coding": [*others, {"system": COLOUR_SYSTEM, "code": colour}]}
    fhir.update(encounter)
    return True


EXECUTORS: dict[str, Callable[..., dict[str, Any]]] = {"recheck_flag": write_recheck_flag}


# ---------- E4-7: notify_staff ----------

# kind -> who reads it. Texts are fixed templates below: they restate IDs, colours and times, never advice.
NOTIFY_ROLES = {"vitals_due": "nurse", "remeasure": "nurse", "clinician_reminder": "clinician",
                "model_unavailable": "nurse", "agent_failed": "nurse"}


def notify_staff(conn: psycopg.Connection, kind: str, proposal_id: str | None = None,
                 visit_id: str | None = None) -> dict[str, Any]:
    """E4-7. Store a fixed-text reminder in afya.notifications for the UI to poll. Never changes the queue.

    vitals_due (visit_id): a reading is due by the site re-check interval.
    remeasure (visit_id, optional proposal_id): staff asked to re-measure.
    clinician_reminder (proposal_id, must be pending): restates the proposal's colour and cited readings.
    model_unavailable (optional visit_id): the language model is down; rule-based scoring continues.
    agent_failed (visit_id): the agent's check of a new reading did not finish (E12-1); look at the patient.
    """
    if kind not in NOTIFY_ROLES:
        return {"status": "invalid", "reason": f"kind must be one of {sorted(NOTIFY_ROLES)}"}
    vid = None
    if visit_id:
        try:
            vid = ref_id(visit_id, "Encounter")
        except ValueError:
            vid = None
        if vid is None or not FHIR_ID.match(vid):
            return {"status": "invalid", "reason": "visit_id is not an Encounter id"}
    proposal = None
    if proposal_id:
        try:
            pid = str(uuid.UUID(str(proposal_id)))
        except ValueError:
            return {"status": "invalid", "reason": "proposal_id is not a UUID"}
        proposal = conn.execute("SELECT id, visit_id, status, obs_id, payload FROM proposals WHERE id = %s",
                                (pid,)).fetchone()
        if proposal is None:
            return {"status": "invalid", "reason": "proposal not found"}
        if vid and vid != proposal["visit_id"]:
            return {"status": "invalid", "reason": "proposal belongs to another visit"}
        vid = proposal["visit_id"]
    if kind in ("vitals_due", "remeasure", "agent_failed") and vid is None:
        return {"status": "invalid", "reason": f"{kind} needs a visit_id"}
    if kind == "clinician_reminder":
        if proposal is None:
            return {"status": "invalid", "reason": "clinician_reminder needs a proposal_id"}
        if proposal["status"] != "pending":
            return {"status": "not_sent", "visit_id": vid, "reason": f"proposal is {proposal['status']}"}
    text = _notification_text(kind, vid, proposal)
    row = conn.execute(
        "INSERT INTO notifications (kind, visit_id, proposal_id, target_role, text) VALUES (%s, %s, %s, %s, %s) "
        "RETURNING id, at", (kind, vid, proposal["id"] if proposal else None, NOTIFY_ROLES[kind], text)).fetchone()
    return {"status": "sent", "notification_id": str(row["id"]), "at": row["at"].isoformat(), "kind": kind,
            "visit_id": vid, "proposal_id": str(proposal["id"]) if proposal else None,
            "target_role": NOTIFY_ROLES[kind], "text": text}


def _notification_text(kind: str, vid: str | None, proposal: dict[str, Any] | None) -> str:
    """Fixed templates. Only IDs, the proposal's colour and its cited readings are filled in."""
    about = ""
    if proposal is not None:
        payload = proposal["payload"] or {}
        cited = ", ".join(f"Observation/{ref_id(o, 'Observation')}"
                          for o in dict.fromkeys([proposal["obs_id"], *payload.get("cited_obs_ids", [])]))
        about = f" Proposal {proposal['id']}: proposed colour {payload.get('to_colour')}, cited readings {cited}."
    if kind == "vitals_due":
        return f"Vitals due for visit {vid} (site re-check interval).{about}"
    if kind == "remeasure":
        return f"Please re-measure the vital signs for visit {vid}.{about}"
    if kind == "clinician_reminder":
        return f"Reminder: a proposal for visit {vid} is waiting for review.{about}"
    if kind == "agent_failed":
        return (f"The automatic check of a new reading for visit {vid} did not finish. Please look at this patient's "
                "latest vitals yourself; the check is retried when the service restarts.")
    where = f" Visit {vid}." if vid else ""
    return ("Language model unavailable: readings are still scored by the fixed rules and colour rises still "
            f"become proposals.{where}")
