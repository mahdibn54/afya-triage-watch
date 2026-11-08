"""Finishing the synthetic eval visits so they leave the waiting room (non-destructive: the Encounter's status becomes
`finished`, nothing is deleted, the same way seed_demo_visit finishes old demo encounters).

Only visits of EV- synthetic eval patients are ever touched: the Patient's label (identifier urn:afya:label) must be
`EV-<case>-<6 hex>`, the label the eval runner gives. P-014 and the seeded demo patients never match. Light module
(httpx only): the runner's cleanup and scripts/finish_eval_visits.py share it."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import httpx

LABEL_SYSTEM = "urn:afya:label"
WAITING = ("arrived", "triaged", "in-progress")
EVAL_LABEL = re.compile(r"EV-[A-Za-z0-9-]+-[0-9a-f]{6}")


def is_eval_label(label: str | None) -> bool:
    return bool(label) and EVAL_LABEL.fullmatch(label) is not None


def patient_label(patient: dict[str, Any]) -> str | None:
    return next((i.get("value") for i in patient.get("identifier", []) if i.get("system") == LABEL_SYSTEM), None)


def select_eval_encounters(resources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """From the Encounters and Patients of a search (with `_include=Encounter:subject`): the waiting Encounters whose
    subject is a Patient with an EV- eval label. An Encounter whose Patient is missing from the results is skipped."""
    items = list(resources)
    eval_patients = {f"Patient/{r['id']}" for r in items
                     if r.get("resourceType") == "Patient" and is_eval_label(patient_label(r))}
    return [r for r in items if r.get("resourceType") == "Encounter" and r.get("status") in WAITING
            and (r.get("subject") or {}).get("reference") in eval_patients]


def find_waiting_eval_encounters(client: httpx.Client, hapi: str) -> list[dict[str, Any]]:
    """Every waiting Encounter of an EV- eval patient (all pages)."""
    found: list[dict[str, Any]] = []
    url: str | None = f"{hapi.rstrip('/')}/Encounter"
    params: dict[str, str] | None = {"status": ",".join(WAITING), "_include": "Encounter:subject", "_count": "200"}
    while url:
        r = client.get(url, params=params)
        r.raise_for_status()
        bundle = r.json()
        found += select_eval_encounters(e["resource"] for e in bundle.get("entry", []))
        url = next((link["url"] for link in bundle.get("link", []) if link.get("relation") == "next"), None)
        params = None
    return found


def finish_encounter(client: httpx.Client, hapi: str, encounter: dict[str, Any]) -> None:
    client.put(f"{hapi.rstrip('/')}/Encounter/{encounter['id']}",
               json={**encounter, "status": "finished"}).raise_for_status()


def finish_visit(client: httpx.Client, hapi: str, visit_id: str) -> bool:
    """Finish one visit the runner just created (its id, bare or `Encounter/<id>`). False when it is not waiting."""
    base, eid = hapi.rstrip("/"), visit_id.split("/")[-1]
    r = client.get(f"{base}/Encounter/{eid}")
    r.raise_for_status()
    enc = r.json()
    if enc.get("status") not in WAITING:
        return False
    finish_encounter(client, hapi, enc)
    return True
