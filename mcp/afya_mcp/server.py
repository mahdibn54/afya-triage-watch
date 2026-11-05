"""afya-mcp: our MCP server.

Two mounts on one port (9000):
  /read/mcp  model-facing, read-only tools (compute_tews, check_deterioration, get_queue_state)
  /act/mcp   executor-only tools (record_vitals, raise_recheck_flag, notify_staff);
             the model's client never connects here.
Every call is audited (audit.py, E4-8). Still stubs: get_queue_state (E4-5), raise_recheck_flag (E4-6), notify_staff (E4-7).
"""
from __future__ import annotations

import contextlib
import os
from functools import lru_cache
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

from . import audit, rules, services
from .db import PgVisitStore
from .fhir import HttpFhir


def _server_settings() -> dict[str, Any]:
    """FastMCP defaults to host 127.0.0.1, which (mcp >= 1.10) turns on DNS-rebinding protection that only accepts
    Host: localhost. Containers call us as http://afya-mcp:9000, so list the accepted hosts explicitly."""
    hosts = [h.strip() for h in os.environ.get("AFYA_MCP_ALLOWED_HOSTS",
                                               "afya-mcp:*,localhost:*,127.0.0.1:*").split(",") if h.strip()]
    try:
        from mcp.server.transport_security import TransportSecuritySettings
    except ImportError:          # mcp 1.9: no Host check at all
        return {"host": "0.0.0.0"}
    return {"host": "0.0.0.0",
            "transport_security": TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                                            allowed_hosts=hosts)}


read = FastMCP("afya-read", stateless_http=True, **_server_settings())
act = FastMCP("afya-act", stateless_http=True, **_server_settings())


async def _run(fn: Any, *args: Any) -> Any:
    """FastMCP calls sync tools on the event loop; the FHIR client is blocking, so run it in a worker thread."""
    return await anyio.to_thread.run_sync(fn, *args)


async def _audited(kind: str, mode: str, inputs: dict[str, Any], fn: Any, actor: str = "agent",
                   run_id: str | None = None) -> Any:
    """E4-8: every tool call goes through audit.call (actor check for act tools, timing, one audit_log row)."""
    return await _run(lambda: audit.call(_auditor(), kind, mode, inputs, fn, actor, run_id))


@lru_cache(maxsize=1)
def _fhir() -> HttpFhir:
    return HttpFhir(os.environ.get("FHIR_BASE_URL", "http://hapi:8080/fhir"))


@lru_cache(maxsize=1)
def _store() -> PgVisitStore | None:
    return PgVisitStore() if os.environ.get("DATABASE_URL") else None


@lru_cache(maxsize=1)
def _auditor() -> audit.PgAuditor | None:
    return audit.PgAuditor() if os.environ.get("DATABASE_URL") else None


@lru_cache(maxsize=1)
def _registry() -> list[dict]:
    return rules.load_registry()


@lru_cache(maxsize=1)
def _plausibility() -> dict:
    return rules.load_plausibility()


@read.tool()
async def compute_tews(observation_id: str, run_id: str | None = None) -> dict:
    """Score one stored vital-signs reading with the SATS chart that fits the patient (fixed code, not you).
    Input: the reading's record ID only, e.g. "Observation/123". Never pass vital-sign numbers.
    Output: status ("scored", "no_chart" for patients without a chart yet, "not_usable"), tews, colour,
    colour_by_tews, signs implied by the inputs, points per input, missing inputs (the colour is then a lower
    bound) and, per input, the record it came from. Quote these record IDs when you explain a flag.
    run_id is filled in by the agent wrapper for the audit log; leave it out."""
    return await _audited("compute_tews", audit.READ, {"observation_id": observation_id},
                          lambda: services.compute_tews(_fhir(), _registry(), observation_id), run_id=run_id)


@read.tool()
async def check_deterioration(visit_id: str, run_id: str | None = None) -> dict:
    """Compare the latest reading of a visit with the previous one and with the colour a nurse last confirmed.
    Input: the visit (Encounter) ID, e.g. "Encounter/v014" or "v014".
    Output: latest and previous score, per-input point changes with the records behind them, and the trigger
    decided by code: trigger.propose=true means a second look must be proposed to the nurse; you cannot cancel
    it and you can never propose a lower colour than trigger.to.
    run_id is filled in by the agent wrapper for the audit log; leave it out."""
    return await _audited("check_deterioration", audit.READ, {"visit_id": visit_id},
                          lambda: services.check_deterioration(_fhir(), _registry(), visit_id), run_id=run_id)


@read.tool()
def get_queue_state() -> dict:
    """Minutes waited against SATS targets, overdue re-checks and unread urgent proposals."""
    raise NotImplementedError("E4-5")


@act.tool()
async def record_vitals(patient_id: str, visit_id: str, values: dict, idempotency_key: str, actor: str,
                        run_id: str | None = None) -> dict:
    """Save a nurse's entry as one FHIR Observation (conditional create on the idempotency key).
    Unknown inputs or values are rejected ("invalid"); impossible values are not saved ("remeasure").
    actor: the user id (afya.users) of the nurse who took the reading, or 'system' for seeded data. Audited."""
    inputs = {"patient_id": patient_id, "visit_id": visit_id, "values": values, "idempotency_key": idempotency_key}
    return await _audited("record_vitals", audit.ACT, inputs,
                          lambda: services.record_vitals(_fhir(), _plausibility(), _registry(), patient_id, visit_id,
                                                         values, idempotency_key, None, _store()),
                          actor=actor, run_id=run_id)


@act.tool()
def raise_recheck_flag(command_id: str, actor: str, run_id: str | None = None) -> dict:
    """Execute an approved command: claim it, write the Flag and confirmed priority, mark done, audit."""
    raise NotImplementedError("E4-6")


@act.tool()
def notify_staff(kind: str, actor: str, proposal_id: str | None = None, visit_id: str | None = None,
                 run_id: str | None = None) -> dict:
    """Send a fixed-text reminder about an existing proposal or an overdue re-check. Adds nothing clinical."""
    raise NotImplementedError("E4-7")


async def health(_request):
    return PlainTextResponse("ok")


@contextlib.asynccontextmanager
async def lifespan(_app):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(read.session_manager.run())
        await stack.enter_async_context(act.session_manager.run())
        yield


app = Starlette(
    routes=[
        Route("/healthz", health),
        Mount("/read", app=read.streamable_http_app()),
        Mount("/act", app=act.streamable_http_app()),
    ],
    lifespan=lifespan,
)
