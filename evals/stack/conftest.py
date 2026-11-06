"""Group A uses real network services and an isolated application-role Postgres connection."""
import asyncio
import os
import time
import uuid

import httpx
import pytest
from afya_mcp import db
from fake_model import ScriptedBackend

from afya_api.agent import Agent
from afya_api.demo_scenario import birth_date
from afya_api.mcp_client import McpGateway
from afya_api.model import Model, ModelSettings

BASE = {"resp_rate": 14, "heart_rate": 80, "systolic_bp": 120, "temperature": 37.0, "spo2": 98,
        "mobility": "walking", "consciousness": "alert", "trauma": "no"}
YELLOW = {**BASE, "resp_rate": 22, "heart_rate": 105}
ORANGE = {**BASE, "resp_rate": 26, "heart_rate": 112, "temperature": 38.6}


class Stack:
    def __init__(self):
        self.gw = McpGateway()
        self.http = httpx.Client(base_url="http://api:8080", timeout=30)
        # HAPI caches searches; the observer must see writes from the immediately preceding assertion.
        self.fhir = httpx.Client(base_url="http://fhir-fault:8081/fhir/", timeout=30,
                                 headers={"Cache-Control": "no-cache"})
        self.control = httpx.Client(base_url="http://fhir-fault:8081", timeout=10)

    def query(self, sql, args=()):
        with db.connect() as conn:
            return conn.execute(sql, args).fetchall()

    def fault(self, mode="off", method="GET", path="", count=0):
        response = self.control.put("/control", json={"mode": mode, "method": method, "path": path,
                                                    "remaining": count})
        response.raise_for_status()

    async def visit(self, colour="GREEN", age=40):
        return (await self.gw.act("seed_demo_visit", {"label": f"GA-{uuid.uuid4().hex[:16]}",
                "birth_date": birth_date(age), "arrived_minutes_ago": 15,
                "confirmed_colour": colour, "actor": "system"}))["visit_id"]

    async def record(self, visit, values, complaint=None, key=None):
        return await self.gw.act("record_vitals", {"visit_id": visit, "values": values, "actor": "nurse-a",
                                 "idempotency_key": key or uuid.uuid4().hex, "complaint": complaint})

    async def run(self, visit, obs, backend=None):
        model = Model(backend or ScriptedBackend(), ModelSettings(call_timeout_s=3, run_timeout_s=60),
                      enabled=backend is not None)
        return await Agent(self.gw, model).run_event(visit, obs, "nurse-a")

    async def proposal(self):
        visit = await self.visit("YELLOW")
        await self.record(visit, YELLOW)
        saved = await self.record(visit, ORANGE)
        result = await self.run(visit, saved["observation_id"])
        assert result["status"] == "paused", result
        return visit, saved["observation_id"], self.props(visit)[0]

    def props(self, visit):
        return self.query("SELECT * FROM proposals WHERE visit_id=%s ORDER BY created_at", (visit,))

    def flags(self, visit):
        response = self.fhir.get("Flag", params={"encounter": f"Encounter/{visit}", "_count": "100"})
        response.raise_for_status()
        return response.json().get("entry", [])

    def colour(self, visit):
        response = self.fhir.get(f"Encounter/{visit}")
        response.raise_for_status()
        coding = response.json().get("priority", {}).get("coding", [])
        return next((c["code"] for c in coding if c.get("system") == "urn:afya:sats-colour"), None)

    def untouched(self, visit, colour):
        assert not self.flags(visit)
        assert self.colour(visit) == colour
        assert not self.query("SELECT * FROM commands WHERE visit_id=%s", (visit,))


@pytest.fixture(scope="session", autouse=True)
def ready(record_testsuite_property):
    if (os.environ.get("GROUP_A_ISOLATED") != "1"
            or not os.environ.get("GROUP_A_PROJECT", "").startswith("afya-e8-2-")):
        raise pytest.UsageError("Group A requires its isolated Compose overlay")
    record_testsuite_property("code_commit", os.environ.get("GROUP_A_COMMIT", "uncommitted"))
    record_testsuite_property("services", "real Postgres/HAPI/nginx/WSO2/afya-mcp/API")
    record_testsuite_property("model", "disabled or scripted boundary; no live model")
    instance = Stack()
    try:
        for attempt in range(90):
            try:
                if (instance.fhir.get("metadata").status_code == 200
                        and instance.http.get("/healthz").status_code == 200):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise RuntimeError("real Group A stack did not become ready")
    finally:
        instance.http.close()
        instance.fhir.close()
        instance.control.close()


@pytest.fixture
def stack():
    if os.environ.get("GROUP_A_ISOLATED") != "1":
        raise pytest.UsageError("Group A requires the isolated evals/stack/compose.yml test stack")
    instance = Stack()
    assert instance.control.get("/healthz").json() == {"group_a_fault_proxy": True}
    assert instance.query("SELECT current_user AS role")[0]["role"] == "afya_app"
    instance.fault()
    yield instance
    instance.fault()
    instance.http.close()
    instance.fhir.close()
    instance.control.close()


def run(coroutine):
    return asyncio.run(coroutine)
