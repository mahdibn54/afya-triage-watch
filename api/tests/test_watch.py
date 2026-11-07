"""E5-7: RED/ORANGE notify at creation; the watch loop reminds (vitals due, unread proposals) and changes nothing."""
from __future__ import annotations

import asyncio
import copy
import uuid
from datetime import UTC, datetime, timedelta

from afya_mcp.fhir import COLOUR_SYSTEM
from conftest import READING
from support import vitals

from afya_api.watch import watch_once

STABLE_YELLOW = dict(READING, resp_rate=22, heart_rate=105, temperature=37.2)


def notes(conn, **where):
    col, val = next(iter(where.items()))
    return [r["kind"] for r in conn.execute(f"SELECT kind FROM notifications WHERE {col} = %s ORDER BY at", (val,))]


def proposal_of(conn, visit):
    return conn.execute("SELECT * FROM proposals WHERE visit_id = %s", (visit,)).fetchone()


def test_orange_proposal_notifies_the_clinician_at_creation(client, as_user, visit, conn):
    vitals(client, visit)
    p = proposal_of(conn, visit)
    assert notes(conn, proposal_id=p["id"]) == ["clinician_reminder"]
    card = next(x for x in client.get("/proposals").json() if x["id"] == str(p["id"]))
    assert "clinician_reminded" in [n["code"] for n in card["notices"]]


def test_yellow_proposal_does_not_notify_at_creation(client, as_user, fhir, conn):
    vid = f"synthetic-test-v-{uuid.uuid4().hex[:10]}"
    fhir.put({"resourceType": "Encounter", "id": vid, "status": "in-progress", "subject": {"reference": "Patient/p1"},
              "priority": {"coding": [{"system": COLOUR_SYSTEM, "code": "GREEN"}]}})
    vitals(client, vid, **STABLE_YELLOW)
    p = proposal_of(conn, vid)
    assert p["payload"]["to_colour"] == "YELLOW" and notes(conn, proposal_id=p["id"]) == []


def test_unread_orange_after_five_minutes_is_reminded_once(client, as_user, visit, conn, gateway):
    vitals(client, visit)
    p = proposal_of(conn, visit)
    gateway.now = datetime.now(UTC) + timedelta(minutes=6)       # six minutes later
    sent = asyncio.run(watch_once(gateway))
    assert str(p["id"]) in sent["clinician_reminder"]
    assert notes(conn, proposal_id=p["id"]) == ["clinician_reminder", "clinician_reminder"]
    again = asyncio.run(watch_once(gateway))
    assert str(p["id"]) not in again["clinician_reminder"]
    assert len(notes(conn, proposal_id=p["id"])) == 2


def test_vitals_due_once_and_nothing_in_the_queue_changes(client, as_user, fhir, conn, gateway):
    vid = f"synthetic-test-v-{uuid.uuid4().hex[:10]}"
    start = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
    fhir.put({"resourceType": "Encounter", "id": vid, "status": "in-progress", "subject": {"reference": "Patient/p1"},
              "period": {"start": start}, "priority": {"coding": [{"system": COLOUR_SYSTEM, "code": "YELLOW"}]}})
    before_fhir = copy.deepcopy(fhir.data)
    before = conn.execute("SELECT id, status, reviewed FROM proposals ORDER BY id").fetchall()
    commands = conn.execute("SELECT count(*) AS n FROM commands").fetchone()["n"]
    sent = asyncio.run(watch_once(gateway))
    assert vid in sent["vitals_due"] and notes(conn, visit_id=vid) == ["vitals_due"]
    assert vid not in asyncio.run(watch_once(gateway))["vitals_due"]
    assert fhir.data == before_fhir                                     # no FHIR write
    assert conn.execute("SELECT id, status, reviewed FROM proposals ORDER BY id").fetchall() == before
    assert conn.execute("SELECT count(*) AS n FROM commands").fetchone()["n"] == commands
    rows = conn.execute("SELECT actor, kind FROM audit_log WHERE kind = 'notify_staff' AND visit_id = %s",
                        (vid,)).fetchall()
    assert [(r["actor"], r["kind"]) for r in rows] == [("agent", "notify_staff")]
