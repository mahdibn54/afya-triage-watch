"""E4-2 record_vitals, E4-3 compute_tews, E4-4 check_deterioration against an in-memory FHIR store."""
from datetime import datetime, timedelta, timezone

import pytest

from afya_mcp import services
from afya_mcp.fhir import COLOUR_SYSTEM, FhirUnavailable, observation_values, vitals_observation
from afya_mcp.rules import load_plausibility, load_registry
from fake_fhir import FakeFhir

REG = load_registry()
LIMITS = load_plausibility()
T0 = datetime(2026, 11, 17, 9, 10, tzinfo=timezone.utc)
BASE = dict(resp_rate=14, heart_rate=80, systolic_bp=120, temperature=37.0,
            mobility="walking", consciousness="alert", trauma="no")


@pytest.fixture
def fhir():
    f = FakeFhir()
    f.put({"resourceType": "Patient", "id": "p014", "birthDate": "1990-03-02"})
    f.put({"resourceType": "Patient", "id": "child", "birthDate": "2020-01-01"})
    f.put({"resourceType": "Encounter", "id": "v014", "status": "in-progress",
           "subject": {"reference": "Patient/p014"},
           "priority": {"coding": [{"system": COLOUR_SYSTEM, "code": "YELLOW"}]}})
    f.put({"resourceType": "Encounter", "id": "vchild", "status": "in-progress",
           "subject": {"reference": "Patient/child"}})
    return f


def record(fhir, values, key, when, patient="p014", visit="v014"):
    return services.record_vitals(fhir, LIMITS, patient, visit, values, key, when)


# ---------- mapping ----------

def test_observation_round_trip():
    obs = vitals_observation("p014", "v014", BASE, "k1", T0)
    assert observation_values(obs) == {**BASE, "resp_rate": 14.0, "heart_rate": 80.0,
                                       "systolic_bp": 120.0, "temperature": 37.0}
    assert obs["identifier"] == [{"system": "urn:afya:req", "value": "k1"}]


# ---------- record_vitals ----------

def test_record_vitals_saves_and_is_idempotent(fhir):
    first = record(fhir, BASE, "key-1", T0)
    again = record(fhir, BASE, "key-1", T0)
    assert first["status"] == "saved"
    assert again["observation_id"] == first["observation_id"]
    assert fhir.creates == 1


def test_record_vitals_rejects_impossible_values_and_saves_nothing(fhir):
    out = record(fhir, {**BASE, "heart_rate": 400}, "key-2", T0)
    assert out["status"] == "remeasure" and not out["saved"]
    assert out["problems"][0]["name"] == "heart_rate"
    assert fhir.creates == 0


# ---------- compute_tews ----------

def test_compute_tews_reads_values_itself_and_cites_the_record(fhir):
    oid = record(fhir, dict(BASE, resp_rate=26, heart_rate=112, temperature=38.6), "k", T0)["observation_id"]
    out = services.compute_tews(fhir, REG, oid)
    assert (out["status"], out["tews"], out["colour"]) == ("scored", 6, "ORANGE")
    assert out["cited"]["heart_rate"] == oid
    assert out["chart_id"] == "sats_adult_2012"


def test_compute_tews_child_has_no_chart_yet(fhir):
    oid = record(fhir, BASE, "kc", T0, patient="child", visit="vchild")["observation_id"]
    assert services.compute_tews(fhir, REG, oid)["status"] == "no_chart"


# ---------- check_deterioration ----------

def test_p014_yellow_to_orange(fhir):
    record(fhir, dict(BASE, resp_rate=22, heart_rate=105, temperature=37.2), "r1", T0)
    record(fhir, dict(BASE, resp_rate=26, heart_rate=112, temperature=38.6), "r2", T0 + timedelta(minutes=40))
    out = services.check_deterioration(fhir, REG, "v014")
    assert out["confirmed_colour"] == "YELLOW"
    assert (out["previous"]["tews"], out["latest"]["tews"]) == (3, 6)
    assert out["trigger"]["propose"] and out["trigger"]["kind"] == "colour_rise"
    assert out["trigger"]["to"] == "ORANGE"
    changed = {c["input"]: (c["points_before"], c["points_after"]) for c in out["changes"]}
    assert changed == {"heart_rate": (1, 2), "temperature": (0, 2)}


def test_improvement_is_logged_not_downgraded(fhir):
    record(fhir, dict(BASE, resp_rate=22, heart_rate=105), "r1", T0)
    record(fhir, BASE, "r2", T0 + timedelta(minutes=30))
    out = services.check_deterioration(fhir, REG, "v014")
    assert not out["trigger"]["propose"] and out["trigger"]["to"] == "YELLOW"


def test_no_readings(fhir):
    assert services.check_deterioration(fhir, REG, "v014")["status"] == "no_readings"


def test_fhir_down_raises_for_the_agent_to_retry(fhir):
    fhir.down = True
    with pytest.raises(FhirUnavailable):
        services.check_deterioration(fhir, REG, "v014")
