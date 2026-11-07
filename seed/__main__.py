"""Run with docker compose --profile seed run --rm seed."""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from afya_mcp import audit, db, rules, services
from afya_mcp.fhir import COLOUR_SYSTEM, Fhir, FhirUnavailable, HttpFhir

from evals.cases import Case, load_cases

ROOT = Path(__file__).resolve().parents[1]
SEED_SYSTEM = "urn:afya:seed:v1"


def require_demo() -> None:
    if os.environ.get("DEMO_MODE") != "1" or os.environ.get("DATA_CLASSIFICATION") != "synthetic":
        raise RuntimeError("Seeding requires DEMO_MODE=1 and DATA_CLASSIFICATION=synthetic")


def seed_case(fhir: Fhir, store: db.VisitStore, auditor: audit.Auditor, case: Case,
              now: datetime) -> dict[str, Any]:
    """Conditional creates preserve the first arrival, baseline and subsequent human decisions on retry."""
    require_demo()
    label = f"SYN-{case.id}"
    key = case.id
    registry, plausibility = rules.load_registry(), rules.load_plausibility()
    first = case.readings[0]
    # Validate before writing any FHIR resources. Later deliberate remeasure inputs are not baseline data.
    problems = services._invalid_entry(first["values"], registry, "seed-v1-baseline")
    problems += services._clean_complaint(first.get("complaint"))[1]
    if problems or rules.check_plausible(first["values"], plausibility):
        raise ValueError(f"{case.id}: invalid baseline")

    def create() -> dict[str, Any]:
        born = now.date() - timedelta(days=round(365.25 * case.age_years) + 30)
        patient = fhir.conditional_create(
            {"resourceType": "Patient", "identifier": [{"system": services.LABEL_SYSTEM, "value": label}],
             "birthDate": born.isoformat(), "gender": "other"}, f"{services.LABEL_SYSTEM}|{label}")
        encounter: dict[str, Any] = {
            "resourceType": "Encounter", "status": "in-progress", "class": {"code": "EMER"},
            "identifier": [{"system": SEED_SYSTEM, "value": key}],
            "subject": {"reference": f"Patient/{patient['id']}"},
            "period": {"start": (now - timedelta(minutes=case.arrived_minutes_ago)).isoformat()},
        }
        if case.confirmed_colour is not None:
            encounter["priority"] = {"coding": [{"system": COLOUR_SYSTEM, "code": case.confirmed_colour}]}
        visit = fhir.conditional_create(encounter, f"{SEED_SYSTEM}|{key}")
        return {"visit_id": visit["id"], "patient_id": patient["id"], "patient_label": label,
                "arrived_at": visit["period"]["start"], "visit_status": visit["status"]}

    visit = audit.call(auditor, "seed_synthetic_visit", audit.ACT, {"case_id": key}, create,
                       actor="system", intent=True)
    if visit["visit_status"] not in services.WAITING_STATUSES:
        return {**visit, "status": "closed_preserved"}
    when = datetime.fromisoformat(visit["arrived_at"])
    result = audit.call(
        auditor, "record_vitals", audit.ACT,
        {"visit_id": visit["visit_id"], "idempotency_key": "seed-v1-baseline"},
        lambda: services.record_vitals(
            fhir, plausibility, registry, visit["patient_id"], visit["visit_id"], first["values"],
            "seed-v1-baseline", when=when, store=store, complaint=first.get("complaint"),
            reported_worsening=first.get("reported_worsening", False)), actor="system", intent=True)
    if result["status"] != "saved":
        raise RuntimeError(f"{case.id}: baseline was not saved ({result['status']})")
    return {**visit, **result}


def main() -> None:
    require_demo()
    cases = load_cases(ROOT / "evals" / "fixtures" / "synthetic")
    if len(cases) != 20:
        raise ValueError("Expected exactly 20 synthetic cases")
    now = datetime.now(UTC)
    fhir = HttpFhir(os.environ["FHIR_BASE_URL"])
    try:
        # HAPI has no container healthcheck and may still be initializing its schema.
        for attempt in range(60):
            try:
                fhir.search("Patient", {"identifier": f"{SEED_SYSTEM}|readiness", "_count": "1"})
                break
            except FhirUnavailable:
                if attempt == 59:
                    raise
                time.sleep(2)
        # Serialize job invocations; conditional FHIR identifiers also recover partial runs.
        with db.connect() as conn:
            conn.execute("SELECT pg_advisory_lock(hashtextextended('afya-seed-v1', 0))")
            for case in cases:
                result = seed_case(fhir, db.PgVisitStore(), audit.PgAuditor(), case, now)
                print(json.dumps({"case_id": case.id, **result}), flush=True)
    finally:
        fhir.client.close()


if __name__ == "__main__":
    main()
