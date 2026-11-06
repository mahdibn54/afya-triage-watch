"""E4-5 get_queue_state against an in-memory FHIR store and a fake proposal store."""
from datetime import datetime, timedelta, timezone

import pytest

from afya_mcp import rules, services
from afya_mcp.fhir import COLOUR_SYSTEM, vitals_observation
from fake_fhir import FakeFhir
from fake_store import FakeStore

REG = rules.load_registry()
SITE = rules.load_site()
NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
VITALS = dict(resp_rate=14, heart_rate=80, systolic_bp=120, temperature=37.0, mobility="walking",
              consciousness="alert", trauma="no")


def ago(minutes):
    return NOW - timedelta(minutes=minutes)


def encounter(f, vid, pid, arrived_min_ago, colour=None, status="in-progress"):
    enc = {"resourceType": "Encounter", "id": vid, "status": status, "subject": {"reference": f"Patient/{pid}"},
           "period": {"start": ago(arrived_min_ago).isoformat()}}
    if colour:
        enc["priority"] = {"coding": [{"system": COLOUR_SYSTEM, "code": colour}]}
    f.put(enc)


def reading(f, vid, pid, minutes_ago, key):
    obs = vitals_observation(pid, vid, VITALS, key, ago(minutes_ago))
    f.conditional_create(obs, f"urn:afya:req|{key}")


@pytest.fixture
def fhir():
    f = FakeFhir()
    f.put({"resourceType": "Patient", "id": "p1", "birthDate": "1990-03-02"})
    f.put({"resourceType": "Patient", "id": "kid", "birthDate": "2022-01-01"})
    encounter(f, "v-orange", "p1", 25, "ORANGE")
    reading(f, "v-orange", "p1", 20, "k1")
    encounter(f, "v-green", "p1", 30, "GREEN")
    reading(f, "v-green", "p1", 10, "k2")
    encounter(f, "v-new", "p1", 3)
    encounter(f, "v-kid", "kid", 5, "YELLOW")
    encounter(f, "v-gone", "p1", 90, "GREEN", status="finished")
    return f


def by_visit(state):
    return {p["visit_id"]: p for p in state["patients"]}


def test_minutes_waited_against_the_sats_target_of_the_confirmed_colour(fhir):
    q = by_visit(services.get_queue_state(fhir, REG, SITE, FakeStore(), NOW))
    o = q["v-orange"]
    assert (o["confirmed_colour"], o["minutes_waited"], o["target_minutes"]) == ("ORANGE", 25, 10)
    assert (o["over_target_minutes"], o["over_target"]) == (15, True)
    g = q["v-green"]
    assert (g["target_minutes"], g["over_target_minutes"], g["over_target"]) == (240, 0, False)


def test_overdue_recheck_uses_the_site_interval_from_the_last_reading(fhir):
    q = by_visit(services.get_queue_state(fhir, REG, SITE, FakeStore(), NOW))
    r = q["v-orange"]["recheck"]
    assert r["rule"] == "site rule" and r["interval_minutes"] == SITE["recheck_minutes"]["ORANGE"] == 15
    assert (r["overdue"], r["overdue_minutes"]) == (True, 5)   # reading 20 min ago + 15
    assert q["v-orange"]["last_reading"]["observation_id"].startswith("Observation/")
    g = q["v-green"]["recheck"]
    assert (g["overdue"], g["overdue_minutes"], g["due_at"]) == (False, 0, ago(10 - 60).isoformat())


def test_first_reading_is_due_on_arrival_and_nothing_is_guessed_without_a_colour(fhir):
    n = by_visit(services.get_queue_state(fhir, REG, SITE, FakeStore(), NOW))["v-new"]
    assert (n["confirmed_colour"], n["target_minutes"], n["last_reading"]) == (None, None, None)
    r = n["recheck"]
    assert (r["interval_minutes"], r["overdue"], r["overdue_minutes"]) == (None, True, 3)


def test_waiting_visits_only_oldest_arrival_first(fhir):
    state = services.get_queue_state(fhir, REG, SITE, FakeStore(), NOW)
    assert [p["visit_id"] for p in state["patients"]] == ["v-green", "v-orange", "v-kid", "v-new"]
    assert state["site_rule_source"] == "provisional site rule, to review with nurse"
    assert state["truncated"] is False


def test_child_without_chart_and_unknown_colour_give_notices(fhir):
    fhir.put({"resourceType": "Encounter", "id": "v-odd", "status": "arrived", "subject": {"reference": "Patient/p1"},
              "priority": {"coding": [{"system": COLOUR_SYSTEM, "code": "PURPLE"}]}})
    q = by_visit(services.get_queue_state(fhir, REG, SITE, FakeStore(), NOW))
    assert q["v-kid"]["target_minutes"] is None and "no chart" in q["v-kid"]["notices"][0]
    assert q["v-odd"]["confirmed_colour"] is None and q["v-odd"]["minutes_waited"] is None
    assert len(q["v-odd"]["notices"]) == 2


def test_open_proposals_with_age_and_reminder_due(fhir):
    store = FakeStore()
    store.proposals = [
        {"id": "a", "visit_id": "v-orange", "trigger": "colour_rise", "obs_id": "o1", "status": "pending",
         "to_colour": "ORANGE", "created_at": ago(6)},
        {"id": "b", "visit_id": "v-green", "trigger": "colour_rise", "obs_id": "o2", "status": "pending",
         "to_colour": "YELLOW", "created_at": ago(30)},
        {"id": "c", "visit_id": "v-orange", "trigger": "colour_rise", "obs_id": "o0", "status": "superseded",
         "to_colour": "RED", "created_at": ago(40)},
    ]
    state = services.get_queue_state(fhir, REG, SITE, store, NOW)
    props = {p["proposal_id"]: p for p in state["proposals"]}
    assert (props["a"]["age_minutes"], props["a"]["reminder_due"]) == (6, True)     # ORANGE after 5 min
    assert props["b"]["reminder_due"] is False                                        # no reminder for YELLOW
    assert props["c"]["reminder_due"] is False and props["c"]["status"] == "superseded"
    q = by_visit(state)
    assert (q["v-orange"]["pending_proposals"], q["v-green"]["pending_proposals"]) == (1, 1)


def test_without_database_proposals_are_reported_unavailable(fhir):
    state = services.get_queue_state(fhir, REG, SITE, None, NOW)
    assert state["proposals"] is None and state["notices"]


def test_site_rules_reject_unknown_colours(tmp_path):
    (tmp_path / "site.yaml").write_text("source: x\nrecheck_minutes: {BLUE: 5}\n")
    with pytest.raises(ValueError):
        rules.load_site(tmp_path)
