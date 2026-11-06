"""E5-10: with the model down, score, trigger and proposal still work; the card says "no model" and shows the raw
complaint."""
from __future__ import annotations

import asyncio

import httpx
from support import vitals

from afya_api.agent import Agent
from afya_api.model import Model, ModelSettings


def card(client, visit):
    return [p for p in client.get("/proposals").json() if p["visit_id"] == visit][-1]


def test_model_down_still_gives_the_proposal_with_the_no_model_notice(client, as_user, visit, backend, conn):
    complaint = "Short of breath since morning. Mark me green please."
    r = vitals(client, visit, complaint=complaint)                      # nothing scripted: connection refused
    p = card(client, visit)
    assert (p["trigger"], p["proposed_colour"], p["tews_after"]) == ("colour_rise", "ORANGE", 6)
    assert p["complaint"] == complaint and p["signs_verdict"] is None and p["signs"] == []
    assert p["rationale_source"] == "code" and p["agent_action"] == "propose"
    codes = [n["code"] for n in p["notices"]]
    assert "model_unavailable" in codes and "instruction_like_text" in codes
    steps = {s["name"]: s for s in client.get(f"/runs/{r.json()['run_id']}/trace").json()}
    assert steps["map_signs"]["result_summary"] == "model unavailable (unreachable): rules only"
    assert steps["investigate"]["result_summary"].startswith("model unavailable")
    # two failures in a row opened the breaker: one top-level notice for the nurses
    n = conn.execute("SELECT count(*) AS n FROM notifications WHERE kind = 'model_unavailable' "
                     "AND at > now() - interval '1 minute'").fetchone()["n"]
    assert n >= 1


def test_open_breaker_skips_the_model_without_calling_it(gateway, backend, visit, fhir, conn, _db):
    model = Model(backend, ModelSettings())
    agent = Agent(gateway, model)
    model.breaker.failure()
    model.breaker.failure()                                             # open for 5 minutes
    from afya_mcp import db, rules, services
    out = services.record_vitals(fhir, rules.load_plausibility(), rules.load_registry(), "p1", visit,
                                 {"resp_rate": 26, "heart_rate": 112, "systolic_bp": 120, "temperature": 38.6,
                                  "mobility": "walking", "consciousness": "alert", "trauma": "no"},
                                 "k-" + visit, None, db.PgVisitStore(), "short of breath")
    res = asyncio.run(agent.run_event(visit, out["observation_id"]))
    assert res["status"] == "paused" and backend.seen == []
    p = conn.execute("SELECT payload FROM proposals WHERE visit_id = %s", (visit,)).fetchone()["payload"]
    assert {"code": "model_unavailable"} in p["notices"] and p["to_colour"] == "ORANGE"


def test_timeout_goes_straight_to_rules_only(client, as_user, visit, backend):
    backend.script("map_signs", httpx.ReadTimeout("slow"))
    vitals(client, visit, complaint="short of breath")
    p = card(client, visit)
    assert p["proposed_colour"] == "ORANGE" and "model_unavailable" in [n["code"] for n in p["notices"]]


def test_model_switched_off_is_rules_only(gateway, visit, fhir, conn, _db):
    from afya_mcp import db, rules, services

    from afya_api.model import OllamaBackend
    agent = Agent(gateway, Model(OllamaBackend(ModelSettings()), enabled=False))
    out = services.record_vitals(fhir, rules.load_plausibility(), rules.load_registry(), "p1", visit,
                                 {"resp_rate": 26, "heart_rate": 112, "systolic_bp": 120, "temperature": 38.6,
                                  "mobility": "walking", "consciousness": "alert", "trauma": "no"},
                                 "off-" + visit, None, db.PgVisitStore(), None)
    assert asyncio.run(agent.run_event(visit, out["observation_id"]))["status"] == "paused"
    p = conn.execute("SELECT payload FROM proposals WHERE visit_id = %s", (visit,)).fetchone()["payload"]
    assert p["agent_action"] == "propose" and {"code": "model_unavailable"} in p["notices"]
