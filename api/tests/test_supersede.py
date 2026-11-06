"""E5-8: newer vitals supersede the older pending proposal; never reviewed -> "not reviewed" until acknowledged."""
from __future__ import annotations

from conftest import READING
from support import error, vitals

STABLE_YELLOW = dict(READING, resp_rate=22, heart_rate=105, temperature=37.2)


def rows(conn, visit):
    return conn.execute("SELECT id, status, reviewed, payload->>'to_colour' AS colour FROM proposals "
                        "WHERE visit_id = %s ORDER BY created_at", (visit,)).fetchall()


def test_newer_reading_supersedes_and_not_reviewed_until_acknowledged(client, as_user, visit, conn):
    vitals(client, visit)                                         # ORANGE proposal
    r = vitals(client, visit, heart_rate=135)                    # TEWS 7 RED: new run
    old, new = rows(conn, visit)
    assert (old["status"], old["reviewed"], old["colour"]) == ("superseded", False, "ORANGE")
    assert (new["status"], new["colour"]) == ("pending", "RED")
    assert r.json()["status"] == "saved"
    sup = [p for p in client.get("/proposals?status=superseded").json() if p["visit_id"] == visit]
    assert [p["id"] for p in sup] == [str(old["id"])] and "not_reviewed" in [n["code"] for n in sup[0]["notices"]]
    error(client.post(f"/proposals/{old['id']}/approve", json={"colour": "ORANGE"}), 409, "conflict")
    r = client.post(f"/proposals/{old['id']}/acknowledge")
    assert r.status_code == 200 and r.json() == {"proposal_id": str(old["id"]), "reviewed": True}
    assert not [p for p in client.get("/proposals?status=superseded").json() if p["visit_id"] == visit]
    error(client.post(f"/proposals/{old['id']}/acknowledge"), 409, "conflict")


def test_a_newer_reading_without_trigger_still_supersedes(client, as_user, visit, conn):
    vitals(client, visit)
    vitals(client, visit, **STABLE_YELLOW)
    assert [r["status"] for r in rows(conn, visit)] == ["superseded"]


def test_a_slow_run_of_an_older_reading_leaves_its_proposal_superseded(client, as_user, visit, conn, fhir,
                                                                       backend):
    """Race: a newer reading is saved while the older reading's run is in map_signs. The older run's proposal is
    saved, then superseded at once by the re-check: it is never left pending."""
    import uuid

    from afya_mcp import db, rules, services
    from fake_model import signs_reply

    def newer_reading_arrives(messages, tools):
        services.record_vitals(fhir, rules.load_plausibility(), rules.load_registry(), "p1", visit, STABLE_YELLOW,
                               uuid.uuid4().hex, None, db.PgVisitStore())
        return signs_reply("none")
    backend.script("map_signs", newer_reading_arrives)
    vitals(client, visit, complaint="tired")
    [p] = rows(conn, visit)
    assert (p["status"], p["reviewed"]) == ("superseded", False)
