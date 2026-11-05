"""afya-mcp: our MCP server.

Two mounts on one port (9000):
  /read/mcp  model-facing, read-only tools (compute_tews, check_deterioration, get_queue_state)
  /act/mcp   executor-only tools (record_vitals, raise_recheck_flag, notify_staff);
             the model's client never connects here.
Still stubs: get_queue_state (E4-5), raise_recheck_flag (E4-6), notify_staff (E4-7).
"""
from __future__ import annotations

import contextlib
import os
from functools import lru_cache

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

from . import rules, services
from .fhir import HttpFhir

read = FastMCP("afya-read", stateless_http=True)
act = FastMCP("afya-act", stateless_http=True)


@lru_cache(maxsize=1)
def _fhir() -> HttpFhir:
    return HttpFhir(os.environ.get("FHIR_BASE_URL", "http://hapi:8080/fhir"))


@lru_cache(maxsize=1)
def _registry() -> list[dict]:
    return rules.load_registry()


@lru_cache(maxsize=1)
def _plausibility() -> dict:
    return rules.load_plausibility()


@read.tool()
def compute_tews(observation_id: str) -> dict:
    """Score one stored reading with the SATS chart that fits the patient. Takes only the record ID
    (e.g. "Observation/123") and reads the values itself; every point cites that record."""
    return services.compute_tews(_fhir(), _registry(), observation_id)


@read.tool()
def check_deterioration(visit_id: str) -> dict:
    """Compare the latest reading of a visit with the previous one and with the colour a nurse last confirmed.
    Returns the changes per vital sign, the records behind them, and the code-decided trigger."""
    return services.check_deterioration(_fhir(), _registry(), visit_id)


@read.tool()
def get_queue_state() -> dict:
    """Minutes waited against SATS targets, overdue re-checks and unread urgent proposals."""
    raise NotImplementedError("E4-5")


@act.tool()
def record_vitals(patient_id: str, visit_id: str, values: dict, idempotency_key: str) -> dict:
    """Save a nurse's entry as one FHIR Observation (conditional create on the idempotency key).
    Impossible values are not saved: the result asks the nurse to re-measure."""
    return services.record_vitals(_fhir(), _plausibility(), patient_id, visit_id, values, idempotency_key)


@act.tool()
def raise_recheck_flag(command_id: str) -> dict:
    """Execute an approved command: claim it, write the Flag and confirmed priority, mark done, audit."""
    raise NotImplementedError("E4-6")


@act.tool()
def notify_staff(kind: str, proposal_id: str | None = None, visit_id: str | None = None) -> dict:
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
