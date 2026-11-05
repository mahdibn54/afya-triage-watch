"""E4-2 DB part with a fake store: the visit row follows the latest FHIR reading."""
from datetime import datetime, timedelta, timezone

import pytest

from afya_mcp import services
from afya_mcp.rules import load_plausibility, load_registry
from fake_fhir import FakeFhir
from fake_store import FakeStore

T0 = datetime(2026, 11, 17, 9, 10, tzinfo=timezone.utc)
BASE = dict(resp_rate=14, heart_rate=80, systolic_bp=120, temperature=37.0,
            mobility="walking", consciousness="alert", trauma="no")


@pytest.fixture
def fhir():
    f = FakeFhir()
    f.put({"resourceType": "Patient", "id": "p1", "birthDate": "1990-03-02"})
    f.put({"resourceType": "Encounter", "id": "v1", "status": "in-progress", "subject": {"reference": "Patient/p1"}})
    return f


def rec(fhir, store, key, when, values=BASE):
    return services.record_vitals(fhir, load_plausibility(), load_registry(), "p1", "v1", values, key, when, store)


def test_saved_reading_sets_latest_obs_id(fhir):
    store = FakeStore()
    out = rec(fhir, store, "k1", T0)
    assert store.visits["v1"] == {"patient_id": "p1", "latest_obs_id": out["observation_id"].split("/")[1]}


def test_newer_reading_moves_latest_and_retry_of_older_does_not(fhir):
    store = FakeStore()
    rec(fhir, store, "k1", T0)
    second = rec(fhir, store, "k2", T0 + timedelta(minutes=30))
    rec(fhir, store, "k1", T0)           # retry of the older entry
    assert store.visits["v1"]["latest_obs_id"] == second["observation_id"].split("/")[1]


def test_nothing_saved_means_no_store_call(fhir):
    store = FakeStore()
    assert rec(fhir, store, "k1", T0, {**BASE, "heart_rate": 400})["status"] == "remeasure"
    assert rec(fhir, store, "k 1", T0)["status"] == "invalid"
    assert store.calls == 0


def test_database_failure_propagates_and_retry_converges(fhir):
    store = FakeStore(fail=True)
    with pytest.raises(ConnectionError):
        rec(fhir, store, "k1", T0)
    assert fhir.creates == 1                     # the Observation is saved, the retry reuses it
    store.fail = False
    out = rec(fhir, store, "k1", T0)
    assert fhir.creates == 1 and store.visits["v1"]["latest_obs_id"] == out["observation_id"].split("/")[1]
