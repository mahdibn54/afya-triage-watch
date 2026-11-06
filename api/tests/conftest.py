"""API tests: FastAPI TestClient with dependency overrides. Postgres is the real one (DATABASE_URL, role afya_app, as
in mcp/tests/test_postgres_integration.py); FHIR is the in-memory fake from mcp/tests and afya-mcp is replaced by an
in-process gateway that runs the same service functions behind the same audit wrapper. Skipped without Postgres."""
from __future__ import annotations

import itertools
import os
import uuid
from typing import Any

import psycopg
import pytest
from afya_mcp import audit, db, rules, services
from afya_mcp.fhir import COLOUR_SYSTEM
from fake_fhir import FakeFhir
from fastapi.testclient import TestClient

from afya_api import deps
from afya_api.main import app
from afya_api.mcp_client import ToolRefused
from afya_api.model import Model, ModelSettings, OllamaBackend


def _reachable() -> bool:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except psycopg.Error:
        return False


DB = _reachable()


@pytest.fixture
def _db() -> None:
    """Tests that touch Postgres depend on this: they are skipped when it is not reachable. Pure unit tests (model
    client, sign validation, wording filter) run everywhere."""
    if not DB:
        pytest.skip("DATABASE_URL not set or Postgres not reachable")

USERS = {"nurse-a": ("Nurse A.", "nurse"), "clin-m": ("Dr. M", "clinician"), "mgr-k": ("Dir. K", "manager")}
REG, LIMITS, SITE = rules.load_registry(), rules.load_plausibility(), rules.load_site()


class InProcessGateway:
    """What afya-mcp does, without HTTP: same functions, same audit wrapper, fake FHIR, real Postgres."""

    def __init__(self, fhir: FakeFhir) -> None:
        self.fhir, self.calls = fhir, []

    async def act(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, args))
        actor, run_id = args["actor"], args.get("run_id")
        if tool == "record_vitals":
            inputs = {k: args.get(k) for k in ("visit_id", "values", "idempotency_key")}
            fn = lambda: services.record_vitals(  # noqa: E731
                self.fhir, LIMITS, REG, args.get("patient_id"), args["visit_id"], args["values"],
                args["idempotency_key"], None, db.PgVisitStore(), args.get("complaint"))
        elif tool == "raise_recheck_flag":
            inputs = {"command_id": args["command_id"]}

            def fn():
                with db.connect() as conn:
                    return services.raise_recheck_flag(self.fhir, conn, args["command_id"], actor, run_id)
        elif tool == "seed_demo_visit":
            inputs = {k: args[k] for k in ("label", "birth_date", "arrived_minutes_ago", "confirmed_colour")}
            fn = lambda: services.seed_demo_visit(  # noqa: E731
                self.fhir, args["label"], args["birth_date"], args["arrived_minutes_ago"], args["confirmed_colour"])
        else:
            raise AssertionError(tool)
        try:
            return audit.call(audit.PgAuditor(), tool, audit.ACT, inputs, fn, actor, run_id)
        except audit.ActorRefused as e:
            raise ToolRefused(str(e)) from e

    async def ui(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "visit_timeline":
            return services.visit_timeline(self.fhir, REG, args["visit_id"])
        if tool == "demo_visit":
            return services.demo_visit(self.fhir, args["label"])
        raise AssertionError(tool)


@pytest.fixture
def fhir(_db) -> FakeFhir:
    f = FakeFhir()
    f._ids = itertools.count(uuid.uuid4().int % 10**12)   # readings.obs_id is global in Postgres, like HAPI ids
    f.put({"resourceType": "Patient", "id": "p1", "birthDate": "1986-03-02",
           "identifier": [{"system": "urn:afya:label", "value": "P-001"}]})
    return f


@pytest.fixture
def visit(fhir) -> str:
    vid = f"v-{uuid.uuid4().hex[:10]}"
    fhir.put({"resourceType": "Encounter", "id": vid, "status": "in-progress", "subject": {"reference": "Patient/p1"},
              "priority": {"coding": [{"system": COLOUR_SYSTEM, "code": "YELLOW"}]}})
    return vid


@pytest.fixture
def gateway(fhir) -> InProcessGateway:
    return InProcessGateway(fhir)


@pytest.fixture
def client(gateway, monkeypatch):
    async def no_sweep(*_a, **_k):   # the sweep has its own tests; here it would touch other tests' leftover commands
        return []
    monkeypatch.setattr("afya_api.main.sweep_on_startup", no_sweep, raising=False)
    monkeypatch.setattr("afya_api.main.get_model", lambda: Model(OllamaBackend(ModelSettings()), enabled=False))
    app.dependency_overrides[deps.get_gateway] = lambda: gateway
    with TestClient(app) as c:   # runs the lifespan too: the startup sweep must not break the app
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def as_user(client):
    def switch(user_id: str) -> None:
        name, role = USERS[user_id]
        app.dependency_overrides[deps.current_user] = lambda: deps.User(id=user_id, name=name, role=role)
    switch("nurse-a")
    return switch


@pytest.fixture
def conn(_db):
    with db.connect() as c:
        yield c


READING = dict(resp_rate=26, heart_rate=112, systolic_bp=120, temperature=38.6, spo2=93, mobility="walking",
               consciousness="alert", trauma="no")
