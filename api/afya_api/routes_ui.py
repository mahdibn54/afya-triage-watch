"""E6-5: data for the evidence, trace and gate screens. Built from audit_log, Postgres and FHIR (through afya-mcp);
no new state."""
from __future__ import annotations

from typing import Any

import psycopg
from afya_mcp import workflow
from fastapi import APIRouter, Depends
from psycopg.rows import DictRow

from . import helpers
from .deps import User, current_user, get_conn, get_gateway
from .errors import ERROR_RESPONSES, ApiError
from .mcp_client import Gateway
from .schemas import Gate, Refusal, Timeline, TraceStep

router = APIRouter(tags=["evidence"])


@router.get("/visits/{visit_id}/timeline", response_model=Timeline, responses=ERROR_RESPONSES)
async def visit_timeline(visit_id: str, _user: User = Depends(current_user),
                         gateway: Gateway = Depends(get_gateway)) -> Timeline:
    """Readings oldest first, raw values from FHIR with points per input (null for SpO2, shown not scored)."""
    try:
        out = await gateway.ui("visit_timeline", {"visit_id": visit_id})
    except Exception as e:
        raise helpers.tool_error(e) from e
    if out["status"] == "not_found":
        raise ApiError(404, "visit not found")
    return Timeline(visit_id=out["visit_id"], chart_id=out["chart_id"], readings=out["readings"])


# ---------- trace ----------

OURS = ("compute_tews", "check_deterioration", "get_queue_state", "record_vitals", "raise_recheck_flag", "notify_staff")
AGENT_STEP = "agent_step"   # written by the agent (E5): payload {step_kind, server, name, args_summary, result_summary,
#                             latency_ms, tokens_in, tokens_out, cost_usd, cited_ids}; free text never goes in
SKIP_ARGS = ("values", "complaint", "complaint_chars")


def _args(inputs: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in inputs.items()
                     if k not in SKIP_ARGS and isinstance(v, (str, int, float)) and not isinstance(v, bool)) or "-"


def _result(kind: str, payload: dict[str, Any]) -> str:
    out = payload.get("output") or {}
    if payload.get("error"):
        return f"error: {payload['error']}"
    status = out.get("status", "ok")
    if kind == "compute_tews" and status == "scored":
        return f"scored: TEWS {out.get('tews')}, {out.get('colour')}"
    if kind == "check_deterioration" and status == "checked":
        trig = out.get("trigger") or {}
        return f"checked: {trig.get('from')} to {trig.get('to')}, {'propose' if trig.get('propose') else 'no proposal'}"
    return str(status)


def _cited(kind: str, payload: dict[str, Any]) -> list[str]:
    inputs, out = payload.get("inputs") or {}, payload.get("output") or {}
    ids: list[Any] = [inputs.get("observation_id"), out.get("observation_id"),
                      (out.get("previous") or {}).get("observation_id"),
                      (out.get("latest") or {}).get("observation_id")]
    return list(dict.fromkeys(workflow.obs_ref(i) for i in ids if i))


def trace_steps(rows: list[dict[str, Any]]) -> list[TraceStep]:
    steps: list[TraceStep] = []
    for r in rows:
        p = r["payload"]
        if r["kind"] in OURS:
            steps.append(TraceStep(
                step=len(steps) + 1, at=r["at"].isoformat(), kind="tool", server="ours", name=r["kind"],
                args_summary=_args(p.get("inputs") or {}), result_summary=_result(r["kind"], p),
                latency_ms=p.get("latency_ms"), cited_ids=_cited(r["kind"], p)))
        elif r["kind"] == AGENT_STEP:
            model = (p.get("model") or {}) if p["step_kind"] == "model" else {}
            steps.append(TraceStep(
                step=len(steps) + 1, at=r["at"].isoformat(), kind=p["step_kind"], server=p.get("server"),
                name=p["name"], args_summary=p.get("args_summary", "-"), result_summary=p.get("result_summary", "-"),
                latency_ms=p.get("latency_ms"), tokens_in=p.get("tokens_in"), tokens_out=p.get("tokens_out"),
                cost_usd=p.get("cost_usd"), provider=model.get("provider"), served_by=model.get("served_by"),
                cited_ids=[workflow.obs_ref(i) for i in p.get("cited_ids", [])]))
    return steps


@router.get("/runs/{run_id}/trace", response_model=list[TraceStep], responses=ERROR_RESPONSES)
def run_trace(run_id: str, _user: User = Depends(current_user), conn: psycopg.Connection[DictRow] = Depends(get_conn)):
    """Ordered steps of one agent run, from audit_log rows with this run_id. Our tools come from the MCP audit rows;
    the agent's own steps (model, decision, gate, borrowed tools) from `agent_step` rows (E5). Unknown run: []."""
    if not workflow.RUN_ID.match(run_id):
        raise ApiError(404, "run not found")
    rows = conn.execute("SELECT id, at, kind, payload FROM audit_log WHERE run_id = %s ORDER BY id",
                        (run_id,)).fetchall()
    return trace_steps(rows)


# ---------- gates ----------

@router.get("/proposals/{proposal_id}/gates", response_model=list[Gate], responses=ERROR_RESPONSES)
def proposal_gates(proposal_id: str, _user: User = Depends(current_user),
                   conn: psycopg.Connection[DictRow] = Depends(get_conn)):
    """Always the six gates in order; `at` is null for a gate not reached. Refused attempts (approve or reject by
    the wrong role, double clicks) hang on `confirmed` with the role of the person who tried."""
    pid = helpers.uuid_or_404(proposal_id)
    p = conn.execute("SELECT * FROM proposals WHERE id = %s", (pid,)).fetchone()
    if p is None:
        raise ApiError(404, "proposal not found")
    cmd = conn.execute("SELECT * FROM commands WHERE proposal_id = %s", (pid,)).fetchone()
    done = conn.execute("SELECT at, actor FROM audit_log WHERE kind = 'command_done' AND payload->>'proposal_id' = %s "
                        "ORDER BY id LIMIT 1", (pid,)).fetchone()
    refused = conn.execute(
        "SELECT a.actor, a.at, u.role FROM audit_log a LEFT JOIN users u ON u.id = a.actor "
        "WHERE a.kind IN ('approve_refused', 'reject_refused') AND a.payload->>'proposal_id' = %s ORDER BY a.id",
        (pid,)).fetchall()
    approved = p["status"] == "approved"
    by = p["decided_by"] if approved else None
    return [
        Gate(gate="proposed", at=p["created_at"].isoformat(), by="agent"),
        Gate(gate="paused", at=p["created_at"].isoformat()),
        Gate(gate="confirmed", at=helpers.iso(p["decided_at"]) if approved else None, by=by,
             refused=[Refusal(by=r["actor"], role=r["role"], at=r["at"].isoformat()) for r in refused]),
        Gate(gate="claimed", at=helpers.iso(cmd["claimed_at"]) if cmd else None,
             by=by if cmd and cmd["claimed_at"] else None),
        Gate(gate="written", at=helpers.iso(cmd["done_at"]) if cmd else None, by=done["actor"] if done else None),
        Gate(gate="audited", at=helpers.iso(done["at"]) if done else None, by=done["actor"] if done else None),
    ]
