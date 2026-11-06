"""E6-6: demo scenario endpoints, and the OpenAPI response models B generates types from."""
from __future__ import annotations

from support import error


def test_demo_endpoints_are_404_unless_demo_mode(client, as_user, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    error(client.post("/demo/scenario", json={"name": "p014"}), 404, "not_found")
    error(client.post("/demo/scenario/next"), 404, "not_found")


def test_demo_scenario_loads_p014_then_the_orange_reading(client, as_user, fhir, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    error(client.post("/demo/scenario/next"), 409, "conflict")
    r = client.post("/demo/scenario", json={"name": "p014"})
    assert r.status_code == 200, r.text
    vid = r.json()["visit_id"]
    patient = next(p for p in fhir.data["Patient"].values() if p["id"] != "p1")
    assert patient["identifier"] == [{"system": "urn:afya:label", "value": "P-014"}] and "name" not in patient
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


def test_openapi_has_response_models_for_the_ui(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path, method in [("/vitals", "post"), ("/proposals", "get"), ("/proposals/{proposal_id}/approve", "post"),
                         ("/proposals/{proposal_id}/reject", "post"), ("/visits/{visit_id}/timeline", "get"),
                         ("/runs/{run_id}/trace", "get"), ("/proposals/{proposal_id}/gates", "get"),
                         ("/demo/scenario", "post"), ("/demo/scenario/next", "post")]:
        ok = paths[path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        assert ok, path
