"""E4-2 record_vitals, E4-3 compute_tews, E4-4 check_deterioration against an in-memory FHIR store."""
from datetime import date, datetime, timedelta, timezone

import pytest

from afya_mcp import services
from afya_mcp.fhir import (
    COLOUR_SYSTEM,
    COMPONENTS,
    FhirUnavailable,
    UnusableObservation,
    age_years,
    observation_values,
    ref_id,
    vitals_observation,
)
from afya_mcp.rules import load_chart, load_plausibility, load_registry
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
    return services.record_vitals(fhir, LIMITS, REG, patient, visit, values, key, when)


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


def test_idempotency_key_is_scoped_to_the_visit(fhir):
    fhir.put({"resourceType": "Patient", "id": "p2", "birthDate": "1985-01-01"})
    fhir.put({"resourceType": "Encounter", "id": "v2", "status": "arrived", "subject": {"reference": "Patient/p2"}})
    a = record(fhir, BASE, "same-key", T0)
    b = record(fhir, BASE, "same-key", T0, patient="p2", visit="v2")
    assert a["observation_id"] != b["observation_id"] and fhir.creates == 2   # another visit: another reading
    obs = fhir.read("Observation", b["observation_id"].split("/")[1])
    assert obs["identifier"] == [{"system": "urn:afya:req", "value": "v2:same-key"}]
    assert record(fhir, BASE, "same-key", T0, patient="p2", visit="v2")["observation_id"] == b["observation_id"]


@pytest.mark.parametrize("status", ["finished", "cancelled", "planned"])
def test_a_visit_that_is_not_open_takes_no_vitals(fhir, status):
    fhir.put({"resourceType": "Encounter", "id": "vdone", "status": status, "subject": {"reference": "Patient/p014"}})
    out = record(fhir, BASE, "k-done", T0, visit="vdone")
    assert out["status"] == "invalid" and not out["saved"] and "not open" in out["problems"][0]
    assert fhir.creates == 0


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


# ---------- audit follow-ups ----------

def test_components_match_the_chart_yaml():
    chart = load_chart()
    for name, spec in chart["numeric"].items():
        assert COMPONENTS[name][1:] == (spec["loinc"], spec["unit"]), name
    assert COMPONENTS["spo2"][1:] == (chart["not_scored"]["spo2"]["loinc"], chart["not_scored"]["spo2"]["unit"])


def test_fahrenheit_is_never_scored_as_celsius(fhir):
    obs = vitals_observation("p014", "v014", BASE, "kf", T0)
    temp = next(c for c in obs["component"] if c["code"]["coding"][0]["code"] == "8310-5")
    temp["valueQuantity"].update(value=98.6, unit="[degF]", code="[degF]")
    with pytest.raises(UnusableObservation):
        observation_values(obs)
    fhir.put({**obs, "id": "f1"})
    assert services.compute_tews(fhir, REG, "Observation/f1")["status"] == "not_usable"


def test_component_with_foreign_system_is_ignored():
    obs = vitals_observation("p014", "v014", {"heart_rate": 80}, "ks", T0)
    obs["component"][0]["code"]["coding"][0]["system"] = "http://example.org"
    assert observation_values(obs) == {}


@pytest.mark.parametrize("values, key", [
    ({**BASE, "hr": 80}, "k"),                       # unknown input would be silently dropped
    ({**BASE, "consciousness": "asleep"}, "k"),      # would only fail later at scoring time
    ({**BASE, "heart_rate": "fast"}, "k"),
    ({}, "k"),
    (BASE, "a&b=c"),                                 # would change the If-None-Exist query
])
def test_record_vitals_rejects_bad_entries_and_saves_nothing(fhir, values, key):
    out = record(fhir, values, key, T0)
    assert out["status"] == "invalid" and not out["saved"]
    assert fhir.creates == 0


def test_record_vitals_refuses_a_visit_of_another_patient(fhir):
    out = record(fhir, BASE, "k", T0, patient="child", visit="v014")
    assert out["status"] == "invalid" and fhir.creates == 0


def test_compute_tews_accepts_bare_id_and_rejects_other_types(fhir):
    oid = record(fhir, BASE, "kb", T0)["observation_id"]
    assert services.compute_tews(fhir, REG, oid.split("/")[1])["status"] == "scored"
    with pytest.raises(ValueError):
        services.compute_tews(fhir, REG, "Patient/p014")


def test_entered_in_error_reading_is_skipped(fhir):
    record(fhir, dict(BASE, resp_rate=22, heart_rate=105), "r1", T0)
    bad = record(fhir, dict(BASE, heart_rate=135, resp_rate=30, mobility="stretcher"), "r2",
                 T0 + timedelta(minutes=30))["observation_id"]
    fhir.data["Observation"][bad.split("/")[1]]["status"] = "entered-in-error"
    out = services.check_deterioration(fhir, REG, "Encounter/v014")
    assert out["latest"]["tews"] == 3 and not out["trigger"]["propose"]


def test_never_confirmed_visit_still_proposes_on_a_rise(fhir):
    fhir.put({"resourceType": "Encounter", "id": "vnew", "status": "in-progress",
              "subject": {"reference": "Patient/p014"}})
    record(fhir, BASE, "n1", T0, visit="vnew")
    assert services.check_deterioration(fhir, REG, "vnew")["trigger"]["propose"] is False   # baseline
    record(fhir, dict(BASE, resp_rate=30, heart_rate=135, mobility="with_help"), "n2", T0 + timedelta(minutes=20),
           visit="vnew")
    out = services.check_deterioration(fhir, REG, "vnew")
    assert out["trigger"]["kind"] == "colour_rise" and out["trigger"]["to"] == "RED"
    assert any("previous reading" in r for r in out["trigger"]["reasons"])


def test_unknown_confirmed_colour_raises(fhir):
    fhir.data["Encounter"]["v014"]["priority"]["coding"][0]["code"] = "BLUE"
    record(fhir, BASE, "u1", T0)
    with pytest.raises(ValueError):
        services.check_deterioration(fhir, REG, "v014")


def test_changes_list_inputs_that_went_missing(fhir):
    record(fhir, BASE, "m1", T0)
    record(fhir, {k: v for k, v in BASE.items() if k != "heart_rate"} | {"resp_rate": 22}, "m2",
           T0 + timedelta(minutes=10))
    changed = {c["input"]: (c["points_before"], c["points_after"])
               for c in services.check_deterioration(fhir, REG, "v014")["changes"]}
    assert changed == {"resp_rate": (0, 2), "heart_rate": (0, None)}


@pytest.mark.parametrize("birth, on, expected_adult", [
    ("2000-06-15", date(2012, 6, 14), False),   # day before 12th birthday
    ("2000-06-15", date(2012, 6, 15), False),   # exactly 12: not "over 12"
    ("2000-06-15", date(2012, 6, 16), True),
    ("2000-02-29", date(2013, 3, 1), True),     # leap-day birthday
])
def test_age_around_the_twelfth_birthday(birth, on, expected_adult):
    assert (age_years({"birthDate": birth}, on) > 12) is expected_adult


def test_partial_birth_dates():
    assert 33 < age_years({"birthDate": "1990-03"}, date(2023, 4, 1)) < 33.1
    assert age_years({"birthDate": "1990"}, date(2023, 4, 1)) == pytest.approx(32.75, abs=0.01)


@pytest.mark.parametrize("ref, expected", [
    ("Patient/1", "1"), ("Patient/1/_history/2", "1"), ("http://h/fhir/Patient/1", "1"), ("1", "1"),
])
def test_ref_id_forms(ref, expected):
    assert ref_id(ref, "Patient") == expected
