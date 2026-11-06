"""E6-1a: GET /queue and GET /audit (docs/api.md sections 5 and 7)."""
from __future__ import annotations

from conftest import READING
from support import vitals

from afya_api.mcp_client import McpUnavailable


def test_queue_matches_the_contract_shape(client, as_user, visit):
    vitals(client, visit, **READING)
    r = client.get("/queue")
    assert r.status_code == 200, r.text
    q = r.json()
    assert set(q) == {"as_of", "site_rule_source", "truncated", "notices", "patients"}   # no internal "proposals"
    [p] = [x for x in q["patients"] if x["visit_id"] == visit]
    assert p["patient_label"] == "P-001" and p["confirmed_colour"] == "YELLOW"
    assert p["target_minutes"] == 60 and p["last_reading"]["observation_id"].startswith("Observation/")
    assert p["recheck"]["rule"] == "site rule" and p["pending_proposals"] == 1      # the reading raised ORANGE


def test_queue_polling_writes_no_audit_rows(client, as_user, visit, conn):
    before = conn.execute("SELECT max(id) AS m FROM audit_log").fetchone()["m"] or 0
    for _ in range(3):
        assert client.get("/queue").status_code == 200
    after = conn.execute("SELECT count(*) AS n FROM audit_log WHERE id > %s AND kind = 'get_queue_state'",
                         (before,)).fetchone()["n"]
    assert after == 0


def test_queue_is_503_when_afya_mcp_is_down(client, as_user, gateway, monkeypatch):
    async def down(*_a, **_k):
        raise McpUnavailable("afya-mcp: OSError")
    monkeypatch.setattr(gateway, "ui", down)
    r = client.get("/queue")
    assert r.status_code == 503 and r.json()["error"]["code"] == "unavailable"


def test_manager_reads_queue_and_audit(client, as_user):
    as_user("mgr-k")
    assert client.get("/queue").status_code == 200
    assert client.get("/audit").status_code == 200


def test_audit_newest_first_filters_and_limit(client, as_user, visit, conn):
    run_id = vitals(client, visit, **READING).json()["run_id"]
    rows = client.get(f"/audit?visit_id={visit}&limit=500").json()
    assert rows and all(r["visit_id"] == visit for r in rows)
    assert [r["id"] for r in rows] == sorted((r["id"] for r in rows), reverse=True)
    assert {"id", "at", "kind", "actor", "auth", "visit_id", "run_id", "payload"} == set(rows[0])
    assert "+00:00" in rows[0]["at"]
    kinds = {r["kind"] for r in rows}
    assert "record_vitals" in kinds and "agent_step" in kinds
    only = client.get(f"/audit?run_id={run_id}&kind=agent_step").json()
    assert only and all(r["run_id"] == run_id and r["kind"] == "agent_step" for r in only)
    assert len(client.get(f"/audit?visit_id={visit}&limit=1").json()) == 1


def test_audit_limit_is_bounded_and_validated(client, as_user):
    assert client.get("/audit?limit=0").status_code == 422
    assert client.get("/audit?limit=501").status_code == 422
    assert client.get("/audit?limit=abc").json()["error"]["code"] == "invalid"
    assert len(client.get("/audit").json()) <= 100


def test_audit_filters_are_parameters_not_sql(client, as_user):
    r = client.get("/audit", params={"visit_id": "x' OR '1'='1"})
    assert r.status_code == 200 and r.json() == []


def test_read_endpoints_need_a_session(client):
    client.cookies.clear()
    for path in ("/queue", "/audit", "/me"):
        assert client.get(path).status_code == 401, path
