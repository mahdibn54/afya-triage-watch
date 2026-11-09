"""E6-5: timeline, trace and gates."""
from __future__ import annotations

import uuid

from afya_mcp import audit
from support import error, new_proposal, vitals


def test_timeline_endpoint(client, as_user, visit):
    vitals(client, visit, resp_rate=None, complaint=None)
    r = client.get(f"/visits/{visit}/timeline")
    assert r.status_code == 200
    body = r.json()
    assert body["visit_id"] == visit and body["chart_id"] == "sats_adult_2012" and len(body["readings"]) == 1
    reading = body["readings"][0]
    assert reading["values"]["spo2"]["points"] is None and reading["values"]["spo2"]["unit"] == "%"
    assert reading["values"]["heart_rate"] == {"value": 112, "unit": "/min", "points": 2}
    assert reading["obs_id"].startswith("Observation/") and reading["complete"] is False
    error(client.get("/visits/nope/timeline"), 404, "not_found")


def test_gates_before_and_after_approval_with_a_refusal(client, as_user, visit, fhir, conn):
    pid, _ = new_proposal(conn, fhir, visit)
    gates = client.get(f"/proposals/{pid}/gates").json()
    assert [g["gate"] for g in gates] == ["proposed", "paused", "confirmed", "claimed", "written", "audited"]
    assert gates[0]["by"] == "agent" and gates[0]["at"] and gates[2]["at"] is None and gates[5]["at"] is None
    as_user("mgr-k")
    client.post(f"/proposals/{pid}/approve", json={"colour": "ORANGE"})
    as_user("nurse-a")
    client.post(f"/proposals/{pid}/approve", json={"colour": "ORANGE"})
    gates = {g["gate"]: g for g in client.get(f"/proposals/{pid}/gates").json()}
    assert gates["confirmed"]["by"] == "nurse-a" and gates["confirmed"]["at"]
    assert [(x["by"], x["role"]) for x in gates["confirmed"]["refused"]] == [("mgr-k", "manager")]
    assert all(gates[g]["at"] for g in ("claimed", "written", "audited"))
    assert gates["written"]["at"] == gates["audited"]["at"]    # one transaction
    error(client.get(f"/proposals/{uuid.uuid4()}/gates"), 404, "not_found")


def test_trace_from_audit_rows(client, as_user, visit, conn):
    run = f"{visit}:1057"
    a = audit.PgAuditor()
    a.write("compute_tews", "agent", "service", visit, run,
            {"mount": "read", "inputs": {"observation_id": "Observation/1057"}, "latency_ms": 38.2,
             "output": {"status": "scored", "tews": 6, "colour": "ORANGE", "observation_id": "Observation/1057"},
             "error": None})
    a.write("check_deterioration", "agent", "service", visit, run,
            {"mount": "read", "inputs": {"visit_id": visit}, "latency_ms": 61.5, "error": None,
             "output": {"status": "checked", "trigger": {"from": "YELLOW", "to": "ORANGE", "propose": True},
                        "previous": {"observation_id": "Observation/1042"},
                        "latest": {"observation_id": "Observation/1057"}}})
    a.write("agent_step", "agent", "service", visit, run,
            {"step_kind": "model", "server": None, "name": "map_signs", "args_summary": "complaint, 66 characters",
             "result_summary": "1 current sign", "latency_ms": 8200, "tokens_in": 540, "tokens_out": 96,
             "cost_usd": 0, "model": {"provider": "groq", "served_by": "groq"}, "cited_ids": []})
    a.write("agent_step", "agent", "service", visit, run,
            {"step_kind": "tool", "server": "borrowed", "name": "search", "cited_ids": ["1042", "Observation/1057"]})
    a.write("raise_recheck_flag_refused", "mgr-k", "demo_switcher", visit, run, {"error": "actor refused"})
    steps = client.get(f"/runs/{run}/trace").json()
    assert [s["step"] for s in steps] == [1, 2, 3, 4]
    assert steps[0] == {"step": 1, "at": steps[0]["at"], "kind": "tool", "server": "ours", "name": "compute_tews",
                        "args_summary": "observation_id=Observation/1057", "result_summary": "scored: TEWS 6, ORANGE",
                        "latency_ms": 38.2, "tokens_in": None, "tokens_out": None, "cost_usd": None,
                        "provider": None, "served_by": None, "cited_ids": ["Observation/1057"]}
    assert steps[1]["result_summary"] == "checked: YELLOW to ORANGE, propose"
    assert steps[1]["cited_ids"] == ["Observation/1042", "Observation/1057"]
    assert (steps[2]["kind"], steps[2]["server"], steps[2]["tokens_in"]) == ("model", None, 540)
    assert (steps[2]["provider"], steps[2]["served_by"], steps[2]["cost_usd"]) == ("groq", "groq", 0)
    assert (steps[3]["server"], steps[3]["cited_ids"]) == ("borrowed", ["Observation/1042", "Observation/1057"])
    assert client.get("/runs/never-ran/trace").json() == []
    error(client.get("/runs/bad id/trace"), 404, "not_found")
