"""afya-mcp: our MCP server.

Three mounts on one port (9000):
  /read/mcp  model-facing, read-only tools (compute_tews, check_deterioration, get_queue_state)
  /act/mcp   executor-only tools (record_vitals, raise_recheck_flag, notify_staff, seed_demo_visit);
             the model's client never connects here.
  /ui/mcp    read-only data for the api's screens (visit_timeline, queue_state, demo_visit); the model's client
             never connects here either, and it is not audited (it changes nothing).
Every call is audited (audit.py, E4-8).
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

from . import audit, db, rules, services
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
ui = FastMCP("afya-ui", stateless_http=True, **_server_settings())


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


@lru_cache(maxsize=1)
def _site() -> dict:
    return rules.load_site()


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
async def get_queue_state(run_id: str | None = None) -> dict:
    """Read-only overview of the waiting room, computed by code. No input needed.
    Output: patients (oldest arrival first), each with visit_id, the colour a nurse confirmed, minutes_waited since
    arrival, the SATS target_minutes for that colour and over_target_minutes; last_reading (record ID and time);
    recheck: when the next reading is due by the site re-check interval (a site rule, not SATS) and whether it is
    overdue; pending_proposals. Then proposals: every proposal not yet decided (status "pending") or superseded but
    not reviewed, with its age in minutes and reminder_due. This tool changes nothing.
    run_id is filled in by the agent wrapper for the audit log; leave it out."""
    return await _audited("get_queue_state", audit.READ, {},
                          lambda: services.get_queue_state(_fhir(), _registry(), _site(), _store()), run_id=run_id)


@act.tool()
async def record_vitals(visit_id: str, values: dict, idempotency_key: str, actor: str, patient_id: str | None = None,
                        run_id: str | None = None, complaint: str | None = None,
                        reported_worsening: bool = False) -> dict:
    """Save a nurse's entry as one FHIR Observation (conditional create on the idempotency key).
    Unknown inputs or values are rejected ("invalid"); impossible values are not saved ("remeasure").
    patient_id: optional, the visit's patient is used when it is left out.
    complaint: optional free text (at most 500 characters after NFKC normalisation), kept in Postgres only and
    never written to FHIR; the audit row records only its length.
    reported_worsening: true when the patient (or the nurse) reports that the patient feels worse; the agent then
    proposes a second look even if the score did not rise (trigger nurse_reported).
    actor: the user id (afya.users) of the nurse who took the reading, or 'system' for seeded data. Audited."""
    inputs = {"patient_id": patient_id, "visit_id": visit_id, "values": values, "idempotency_key": idempotency_key,
              "complaint_chars": len(complaint) if isinstance(complaint, str) else None,
              "reported_worsening": reported_worsening}
    return await _audited("record_vitals", audit.ACT, inputs,
                          lambda: services.record_vitals(_fhir(), _plausibility(), _registry(), patient_id, visit_id,
                                                         values, idempotency_key, None, _store(), complaint,
                                                         reported_worsening),
                          actor=actor, run_id=run_id)


@act.tool()
async def raise_recheck_flag(command_id: str, actor: str, run_id: str | None = None) -> dict:
    """Executor only. Run a nurse-approved command (input: its command_id only): claim it (or resume it after a
    crash), write the FHIR Flag "second look" citing the readings and set the confirmed colour on
    Encounter.priority, then mark it done and audit, through the executor registered for commands.action_type.
    Safe to retry: the same command always gives the same Flag.
    actor: the user id who approved the proposal, or 'agent'/'system' for the startup sweep and retries.
    Output status: done, already_done, refused (with reason), in_progress, not_found or invalid."""
    def run() -> dict:
        with db.connect() as conn:
            return services.raise_recheck_flag(_fhir(), conn, command_id, actor, run_id)
    return await _audited("raise_recheck_flag", audit.ACT, {"command_id": command_id}, run, actor=actor,
                          run_id=run_id)


@act.tool()
async def notify_staff(kind: str, actor: str, proposal_id: str | None = None, visit_id: str | None = None,
                       run_id: str | None = None) -> dict:
    """Executor and watch loop only. Store a fixed-text reminder for the nurse UI to show; it restates an existing
    proposal's colour and cited record IDs or says vitals are due. Adds nothing clinical; never changes the queue.
    kind: 'vitals_due' (needs visit_id), 'remeasure' (needs visit_id, proposal_id optional), 'clinician_reminder'
    (needs a pending proposal_id), 'model_unavailable' (visit_id optional), 'agent_failed' (needs visit_id).
    actor: user id from afya.users ('agent' or 'system' when automated). Output: status sent, invalid or not_sent."""
    def run() -> dict:
        with db.connect() as conn:
            return services.notify_staff(conn, kind, proposal_id, visit_id)
    inputs = {"kind": kind, "proposal_id": proposal_id, "visit_id": visit_id}
    return await _audited("notify_staff", audit.ACT, inputs, run, actor=actor, run_id=run_id)


@act.tool()
async def seed_demo_visit(label: str, birth_date: str, arrived_minutes_ago: int, confirmed_colour: str | None,
                          actor: str, run_id: str | None = None) -> dict:
    """Demo only (DEMO_MODE=1): create the synthetic patient with this label (identifier urn:afya:label, no name) and
    a fresh waiting visit (confirmed_colour=None leaves it unconfirmed). Earlier waiting visits of that demo patient are
    finished. Refused when DEMO_MODE is not 1. actor: 'system'. Audited."""
    def run() -> dict:
        if os.environ.get("DEMO_MODE") != "1":
            return {"status": "refused", "reason": "DEMO_MODE is not 1"}
        return services.seed_demo_visit(_fhir(), label, birth_date, arrived_minutes_ago, confirmed_colour)
    inputs = {"label": label, "birth_date": birth_date, "arrived_minutes_ago": arrived_minutes_ago,
              "confirmed_colour": confirmed_colour}
    return await _audited("seed_demo_visit", audit.ACT, inputs, run, actor=actor, run_id=run_id)


@ui.tool()
async def visit_timeline(visit_id: str) -> dict:
    """Read-only, for the api: the readings of one visit, oldest first, with raw values and points per input."""
    return await _run(lambda: services.visit_timeline(_fhir(), _registry(), visit_id))


@ui.tool()
async def queue_state() -> dict:
    """Read-only, for the api's waiting-room board (GET /queue, polled every few seconds by every screen). Same data
    as get_queue_state, but on this mount so the screens' polling is not written to the audit log as agent calls."""
    return await _run(lambda: services.get_queue_state(_fhir(), _registry(), _site(), _store()))


@ui.tool()
async def demo_visit(label: str) -> dict:
    """Read-only, for the api: the waiting visit of the demo patient with this label and its number of readings."""
    return await _run(lambda: services.demo_visit(_fhir(), label))


async def health(_request):
    return PlainTextResponse("ok")


@contextlib.asynccontextmanager
async def lifespan(_app):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(read.session_manager.run())
        await stack.enter_async_context(act.session_manager.run())
        await stack.enter_async_context(ui.session_manager.run())
        yield


app = Starlette(
    routes=[
        Route("/healthz", health),
        Mount("/read", app=read.streamable_http_app()),
        Mount("/act", app=act.streamable_http_app()),
        Mount("/ui", app=ui.streamable_http_app()),
    ],
    lifespan=lifespan,
)
