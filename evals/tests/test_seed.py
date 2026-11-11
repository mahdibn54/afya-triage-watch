"""E2-6 retry, partial failure and preservation contract; no model calls."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone

import pytest
from afya_mcp import audit, identity, services
from seed.__main__ import ROOT, load_seed_cases, seed_case

# Reuse the MCP suite's in-memory FHIR implementation without importing the installed MCP SDK's tests.
spec = importlib.util.spec_from_file_location("seed_fake_fhir", ROOT / "mcp/tests/fake_fhir.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
FakeFhir = module.FakeFhir


class Store:
    def __init__(self):
        self.visits = {}
        self.fail = False

    def record_reading(self, visit_id, patient_id, latest_obs_id, patient_label=None, **kw):
        if self.fail:
            raise ConnectionError("database unavailable")
        self.visits[visit_id] = (patient_id, latest_obs_id, patient_label)


class Auditor:
    def __init__(self):
        self.rows = []
        self.fail = False

    def role(self, actor):
        return "system"

    def write(self, *args):
        if self.fail:
            raise ConnectionError("audit unavailable")
        self.rows.append(args)


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DATA_CLASSIFICATION", "synthetic")
    return FakeFhir(), Store(), Auditor(), load_seed_cases()


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def test_seed_baselines_are_idempotent_and_preserve_confirmations(setup):
    fhir, store, auditor, cases = setup
    first = [seed_case(fhir, store, auditor, c, NOW) for c in cases]
    assert len(cases) == 24 and len(store.visits) == 24
    assert {k: len(v) for k, v in fhir.data.items()} == {"Patient": 24, "Encounter": 24, "Observation": 24}
    visit = fhir.read("Encounter", first[0]["visit_id"])
    visit["priority"]["coding"][0]["code"] = "RED"
    fhir.update(visit)
    again = [seed_case(fhir, store, auditor, c, NOW + timedelta(days=1)) for c in cases]
    assert first == again
    assert fhir.creates == 72
    assert fhir.read("Encounter", visit["id"])["priority"]["coding"][0]["code"] == "RED"
    unconfirmed = next(r for c, r in zip(cases, first) if c.confirmed_colour is None)
    assert "priority" not in fhir.read("Encounter", unconfirmed["visit_id"])
    assert all(row[1:3] == ("system", "service") for row in auditor.rows)
    assert {row[0] for row in auditor.rows} == {
        "seed_synthetic_visit_started", "seed_synthetic_visit", "record_vitals_started", "record_vitals"}


def test_retry_after_database_failure_repairs_visit_without_duplicate_fhir(setup):
    fhir, store, auditor, cases = setup
    store.fail = True
    with pytest.raises(ConnectionError):
        seed_case(fhir, store, auditor, cases[0], NOW)
    store.fail = False
    result = seed_case(fhir, store, auditor, cases[0], NOW + timedelta(days=1))
    assert fhir.creates == 3 and result["visit_id"] in store.visits


def test_closed_visit_stays_closed(setup):
    fhir, store, auditor, cases = setup
    result = seed_case(fhir, store, auditor, cases[0], NOW)
    visit = fhir.read("Encounter", result["visit_id"])
    fhir.update({**visit, "status": "finished"})
    assert seed_case(fhir, store, auditor, cases[0], NOW)["status"] == "closed_preserved"
    assert fhir.creates == 3


@pytest.mark.parametrize("name,value", [("DEMO_MODE", "0"), ("DATA_CLASSIFICATION", "real")])
def test_guard_refuses_before_writing(setup, monkeypatch, name, value):
    fhir, store, auditor, cases = setup
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        seed_case(fhir, store, auditor, cases[0], NOW)
    assert fhir.creates == 0 and not auditor.rows


def test_failed_audit_prevents_effects(setup):
    fhir, store, auditor, cases = setup
    auditor.fail = True
    with pytest.raises(audit.AuditFailed):
        seed_case(fhir, store, auditor, cases[0], NOW)
    assert fhir.creates == 0


def test_retry_preserves_newer_readings_and_complaint(setup):
    fhir, store, auditor, cases = setup
    case = cases[0]
    result = seed_case(fhir, store, auditor, case, NOW)
    from afya_mcp import rules
    saved = services.record_vitals(
        fhir, rules.load_plausibility(), rules.load_registry(), result["patient_id"], result["visit_id"],
        case.readings[1]["values"], "human-recheck", when=NOW, store=store)
    seed_case(fhir, store, auditor, case, NOW + timedelta(days=1))
    assert store.visits[result["visit_id"]][1] == saved["observation_id"].split("/")[1]


def test_seeded_patients_get_made_up_names_kept_out_of_audit(setup):
    fhir, store, auditor, cases = setup
    result = seed_case(fhir, store, auditor, cases[0], NOW)
    patient = fhir.read("Patient", result["patient_id"])
    name = identity.full_name_of(patient)
    assert name == " ".join(identity.name_for(f"SYN-{cases[0].id}"))
    assert identity.file_number_of(patient) == identity.file_number_for(f"SYN-{cases[0].id}")
    assert name not in json.dumps(result)
    assert name not in json.dumps(getattr(auditor, "rows", []), default=str)


def test_demo_patients_start_without_a_complaint(setup):
    """The demo-video patients get their first reading only; the nurse types the complaint live."""
    fhir, store, auditor, cases = setup
    demo = [c for c in cases if not c.id.startswith("b")]
    assert [c.id for c in demo] == ["n02-worst-headache", "m05-neighbour-blood", "m16-french-negation",
                                    "n06-french-blood-vomit"]
    for c in demo:
        seed_case(fhir, store, auditor, c, NOW)
        assert c.readings[0]["complaint"] is None
