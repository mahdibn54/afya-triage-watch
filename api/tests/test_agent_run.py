"""E5-2: the event run graph, end to end through the api (real Postgres + checkpoints, fake FHIR, scripted model)."""
from __future__ import annotations

import uuid

from afya_mcp.fhir import COLOUR_SYSTEM
from conftest import READING
from support import vitals

STABLE_YELLOW = dict(READING, resp_rate=22, heart_rate=105, temperature=37.2)   # TEWS 3, YELLOW


def proposals_of(conn, visit):
    return conn.execute("SELECT * FROM proposals WHERE visit_id = %s ORDER BY created_at", (visit,)).fetchall()


def trace_names(client, run_id):
    return [(s["kind"], s["name"]) for s in client.get(f"/runs/{run_id}/trace").json()]


def checkpoints(conn, run_id):
    return conn.execute("SELECT count(*) AS n FROM lg.checkpoints WHERE thread_id = %s", (run_id,)).fetchone()["n"]


def test_colour_rise_creates_one_proposal_pauses_then_approval_resumes_the_graph(client, as_user, visit, fhir,
                                                                                 conn, gateway):
    r = vitals(client, visit)
    assert r.status_code == 200 and r.json()["status"] == "saved"
    run_id = r.json()["run_id"]
    [p] = proposals_of(conn, visit)
    assert p["status"] == "pending" and p["trigger"] == "colour_rise" and p["obs_id"] == run_id.split(":")[1]
    pay = p["payload"]
    assert (pay["current_colour"], pay["to_colour"], pay["tews_after"], pay["agent_action"]) == \
        ("YELLOW", "ORANGE", 6, "propose")
    assert pay["rationale_source"] == "code" and pay["reasons"][0].startswith("colour rise YELLOW -> ORANGE")
    names = trace_names(client, run_id)
    for step in [("gate", "validate"), ("tool", "record_vitals"), ("tool", "compute_tews"),
                 ("tool", "check_deterioration"), ("decision", "trigger"), ("decision", "submit_decision"),
                 ("gate", "paused_for_nurse")]:
        assert step in names, (step, names)
    assert checkpoints(conn, run_id) > 0                       # LangGraph checkpoints in Postgres schema lg
    assert not fhir.data.get("Flag")                           # paused: nothing written

    r = client.post(f"/proposals/{p['id']}/approve", json={"colour": "ORANGE"})
    assert r.status_code == 200, r.text
    cid = r.json()["command_id"]
    assert ("raise_recheck_flag", {"command_id": cid, "actor": "nurse-a", "run_id": run_id}) in gateway.calls
    assert len(fhir.data["Flag"]) == 1
    assert {"system": COLOUR_SYSTEM, "code": "ORANGE"} in fhir.data["Encounter"][visit]["priority"]["coding"]
    assert ("tool", "raise_recheck_flag") in trace_names(client, run_id)   # the executor ran inside the run


def test_retry_of_the_same_reading_does_not_run_twice(client, as_user, visit, conn):
    key = uuid.uuid4().hex
    first = vitals(client, visit, key=key).json()
    again = vitals(client, visit, key=key).json()
    assert first["run_id"] == again["run_id"]
    assert len(proposals_of(conn, visit)) == 1


def test_no_trigger_is_logged_only(client, as_user, visit, conn):
    r = vitals(client, visit, **STABLE_YELLOW)
    assert len(proposals_of(conn, visit)) == 0
    steps = client.get(f"/runs/{r.json()['run_id']}/trace").json()
    trig = next(s for s in steps if s["name"] == "trigger")
    assert trig["result_summary"].startswith("log only: no colour change")


def test_first_reading_without_a_confirmed_colour_is_a_baseline(client, as_user, fhir, conn):
    vid = f"v-{uuid.uuid4().hex[:10]}"
    fhir.put({"resourceType": "Encounter", "id": vid, "status": "in-progress", "subject": {"reference": "Patient/p1"}})
    r = vitals(client, vid)                                   # TEWS 6, but nothing to compare with
    assert len(proposals_of(conn, vid)) == 0
    trig = next(s for s in client.get(f"/runs/{r.json()['run_id']}/trace").json() if s["name"] == "trigger")
    assert trig["result_summary"] == "log only: first reading: baseline only"
    r = vitals(client, vid, **dict(READING, heart_rate=135))   # second reading: compared with the first
    [p] = proposals_of(conn, vid)
    assert p["payload"]["to_colour"] == "RED" and p["payload"]["current_colour"] == "ORANGE"


def test_impossible_value_is_a_remeasure_and_starts_no_run(client, as_user, visit, conn):
    r = vitals(client, visit, heart_rate=400)
    assert r.json()["status"] == "remeasure" and "run_id" not in r.json()
    assert len(proposals_of(conn, visit)) == 0
    n = conn.execute("SELECT count(*) AS n FROM audit_log WHERE kind = 'agent_step' AND visit_id = %s",
                     (visit,)).fetchone()["n"]
    assert n == 0


def test_older_reading_run_stops_when_a_newer_one_exists(client, as_user, visit, agent, conn):
    import asyncio
    old = vitals(client, visit, **STABLE_YELLOW).json()["observation_id"]
    vitals(client, visit, **STABLE_YELLOW)
    out = asyncio.run(agent.run_event(visit, old + "-not-latest"))
    assert out["status"] == "ended" and out["stop"].startswith("a newer reading exists")
