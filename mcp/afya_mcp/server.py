"""afya-mcp: our MCP server.

Two mounts on one port (9000):
  /read/mcp  model-facing, read-only tools (compute_tews, check_deterioration, get_queue_state)
  /act/mcp   executor-only tools (record_vitals, raise_recheck_flag, notify_staff); the model's client never connects here
Tool bodies beyond compute_tews are filled in during E4 (see docs/Afya_Tasks_BMAD.md).
"""
from __future__ import annotations

import contextlib

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

from . import rules

read = FastMCP("afya-read", stateless_http=True)
act = FastMCP("afya-act", stateless_http=True)


@read.tool()
def compute_tews(observation_id: str) -> dict:
    """Score one stored reading with the SATS chart that fits the patient. Reads the values itself."""
    raise NotImplementedError("E4-3: read the Observation from FHIR, then rules.score()")


@read.tool()
def check_deterioration(patient_id: str) -> dict:
    """Compare the latest scored reading with earlier ones; return the change, trigger type and cited records."""
    raise NotImplementedError("E4-4")


@read.tool()
def get_queue_state() -> dict:
    """Minutes waited against SATS targets, overdue re-checks and unread urgent proposals."""
    raise NotImplementedError("E4-5")


@act.tool()
def record_vitals(visit_id: str, observations: list[dict], idempotency_key: str) -> dict:
    """Save a nurse's entry as FHIR Observations (conditional create) and return their ids."""
    raise NotImplementedError("E4-2")


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
