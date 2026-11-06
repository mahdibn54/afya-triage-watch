"""Helpers shared by the API tests."""
from __future__ import annotations

import uuid

from afya_mcp import db, services, workflow
from conftest import READING

GOOD = {"to_colour": "ORANGE", "current_colour": "YELLOW", "tews_before": 3, "tews_after": 6,
        "reasons": ["colour rise YELLOW -> ORANGE (TEWS 6)"], "rationale_source": "code", "agent_action": "propose",
        "signs_verdict": "found", "cited_obs_ids": [], "rationale": "Please take a second look.",
        "signs": [{"code": "SOB_ACUTE", "gloss": "sudden shortness of breath", "colour": "ORANGE",
                   "source": "complaint", "status": "current", "quote": "Short of breath",
                   "quote_span": {"start": 0, "end": 15}, "reason": None}]}


def error(r, status, code):
    assert r.status_code == status, r.text
    assert set(r.json()) == {"error"} and r.json()["error"]["code"] == code
    return r.json()["error"]


def vitals(client, visit, key=None, **extra):
    return client.post("/vitals", json={"visit_id": visit, "idempotency_key": key or uuid.uuid4().hex,
                                        **READING, **extra})


def new_proposal(conn, fhir, visit, payload=None):
    """What the agent (E5) will do: a reading, then a proposal for it."""
    out = services.record_vitals(fhir, services.rules.load_plausibility(), services.rules.load_registry(), "p1",
                                 visit, READING, uuid.uuid4().hex, None, db.PgVisitStore())
    oid = out["observation_id"].split("/")[1]
    payload = {**(payload or GOOD), "cited_obs_ids": [oid]}
    p = workflow.insert_proposal(conn, visit, "colour_rise", oid, workflow.evidence_hash([oid], ["SOB"], "r"), payload)
    return str(p["id"]), oid
