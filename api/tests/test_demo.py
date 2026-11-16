"""E6-6: demo scenario endpoints, and the OpenAPI response models B generates types from."""
from __future__ import annotations

from support import error


def test_demo_endpoints_are_404_unless_demo_mode(client, as_user, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    error(client.post("/demo/scenario", json={"name": "p014"}), 404, "not_found")
    error(client.post("/demo/scenario/next"), 404, "not_found")
    error(client.post("/demo/waiting-room"), 404, "not_found")
    error(client.get("/demo/waiting-room/reset"), 404, "not_found")


def test_demo_scenario_loads_p014_then_the_orange_reading(client, as_user, fhir, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    error(client.post("/demo/scenario/next"), 409, "conflict")
    r = client.post("/demo/scenario", json={"name": "p014"})
    assert r.status_code == 200, r.text
    vid = r.json()["visit_id"]
    patient = next(p for p in fhir.data["Patient"].values() if p["id"] != "p1")
    assert patient["identifier"][0] == {"system": "urn:afya:label", "value": "P-014"}
    assert patient["name"][0]["text"] == "Grace Achieng"   # made-up, fixed for the demo patient
    tl = client.get(f"/visits/{vid}/timeline").json()
    assert [(x["tews"], x["colour"]) for x in tl["readings"]] == [(3, "YELLOW")]
    nxt = client.post("/demo/scenario/next")
    assert nxt.status_code == 200 and nxt.json()["obs_id"].startswith("Observation/")
    tl = client.get(f"/visits/{vid}/timeline").json()
    assert [(x["tews"], x["colour"]) for x in tl["readings"]] == [(3, "YELLOW"), (6, "ORANGE")]
    error(client.post("/demo/scenario/next"), 409, "conflict")
    # the body is optional and loading again starts a fresh visit
    again = client.post("/demo/scenario").json()["visit_id"]
    assert again != vid and fhir.data["Encounter"][vid]["status"] == "finished"
    assert client.post("/demo/scenario/next").status_code == 200


def test_openapi_has_response_models_for_the_ui(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    paths = client.get("/openapi.json").json()["paths"]
    for path, method in [("/vitals", "post"), ("/proposals", "get"), ("/proposals/{proposal_id}/approve", "post"),
                         ("/proposals/{proposal_id}/reject", "post"), ("/visits/{visit_id}/timeline", "get"),
                         ("/runs/{run_id}/trace", "get"), ("/proposals/{proposal_id}/gates", "get"),
                         ("/demo/scenario", "post"), ("/demo/scenario/next", "post"), ("/demo/waiting-room", "post")]:
        ok = paths[path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        assert ok, path


def _demo_rows(conn, actor, kind="demo_scenario"):
    return [dict(r) for r in conn.execute("SELECT actor, auth, visit_id, payload FROM audit_log WHERE kind = %s "
                                          "AND actor = %s ORDER BY id DESC LIMIT 2", (kind, actor))]


def test_demo_is_nurse_or_clinician_only_and_every_click_is_audited_with_the_user(client, as_user, conn, monkeypatch):
    """E12-3: a manager (read only) gets 403 and the refusal is audited; a nurse's clicks are audited with her id."""
    monkeypatch.setenv("DEMO_MODE", "1")
    as_user("mgr-k")
    before = conn.execute("SELECT count(*) AS n FROM audit_log WHERE kind = 'demo_scenario_refused' "
                          "AND actor = 'mgr-k'").fetchone()["n"]
    error(client.post("/demo/scenario", json={"name": "p014"}), 403, "forbidden")
    error(client.post("/demo/scenario/next"), 403, "forbidden")
    after = conn.execute("SELECT count(*) AS n FROM audit_log WHERE kind = 'demo_scenario_refused' "
                         "AND actor = 'mgr-k'").fetchone()["n"]
    assert after == before + 2
    as_user("clin-m")
    vid = client.post("/demo/scenario").json()["visit_id"]
    obs = client.post("/demo/scenario/next").json()["obs_id"]
    nxt, load = _demo_rows(conn, "clin-m")
    assert load["visit_id"] == nxt["visit_id"] == vid and load["auth"] == nxt["auth"] == "demo_switcher"
    assert load["payload"]["action"] == "load" and load["payload"]["scenario"] == "p014"
    assert nxt["payload"] == {"action": "next", "scenario": "p014", "reading": 2, "obs_id": obs}


def test_fresh_waiting_room_reloads_the_27_patients_arriving_now(client, as_user, fhir, monkeypatch):
    """A fresh waiting room for a demo: every synthetic patient gets a new visit that started 2 to 30 minutes ago,
    with its first reading; loading again finishes the previous visits instead of deleting them."""
    from afya_api.waiting_room import PATIENTS
    monkeypatch.setenv("DEMO_MODE", "1")
    r = client.post("/demo/waiting-room")
    assert r.status_code == 200, r.text
    assert r.json()["patients"] == len(PATIENTS) == 27
    first = {e["id"] for e in fhir.data["Encounter"].values() if e["status"] == "in-progress"
             and e.get("identifier", [{}])[0].get("system") == "urn:afya:demo"}
    assert len(first) == 27
    again = client.post("/demo/waiting-room")
    assert again.status_code == 200, again.text
    assert all(fhir.data["Encounter"][v]["status"] == "finished" for v in first)


def test_fresh_waiting_room_is_nurse_or_clinician_only(client, as_user, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    as_user("mgr-k")
    error(client.post("/demo/waiting-room"), 403, "forbidden")
    error(client.get("/demo/waiting-room/reset"), 403, "forbidden")


def test_fresh_waiting_room_from_a_browser_url(client, as_user, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    r = client.get("/demo/waiting-room/reset")
    assert r.status_code == 200, r.text
    assert r.json()["patients"] == 27


def test_audit_since_reset_hides_older_rows_without_deleting_them(client, as_user, conn, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    client.post("/demo/scenario")                      # an older row, before the reset
    total_before = conn.execute("SELECT count(*) AS n FROM audit_log").fetchone()["n"]
    assert client.get("/demo/waiting-room/reset").status_code == 200
    reset_id = conn.execute("SELECT max(id) AS id FROM audit_log WHERE kind = 'demo_scenario' "
                            "AND payload->>'action' = 'waiting_room'").fetchone()["id"]
    rows = client.get("/audit", params={"since_reset": "true", "limit": 500}).json()
    assert rows and all(r["id"] >= reset_id for r in rows)
    assert any(r["kind"] == "demo_scenario" and r["payload"].get("action") == "waiting_room" for r in rows)
    assert sum(r["kind"] == "seed_demo_visit" for r in rows) == 27   # the reload's own rows, and no older ones
    assert conn.execute("SELECT count(*) AS n FROM audit_log").fetchone()["n"] > total_before   # nothing deleted
