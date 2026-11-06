"""E5-2: the agent's own trace rows (docs/api.md section 7).

Each step of a run is one audit_log row with the run's run_id, so GET /runs/{run_id}/trace can show it:
- steps that call one of OUR tools (compute_tews, check_deterioration, get_queue_state, raise_recheck_flag,
  notify_staff) are recorded by afya-mcp's own audit row, because the agent passes the run_id to the tool;
- every other step writes an `agent_step` row here: payload {step_kind, server, name, args_summary, result_summary,
  latency_ms, tokens_in, tokens_out, cost_usd, cited_ids} plus, for model calls, a `model` object (tag, digest,
  seed, settings, durations). IDs, codes and numbers only: never the complaint, a quote or FHIR text.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from afya_mcp import db
from psycopg.types.json import Jsonb

log = logging.getLogger("afya_api.steps")

STEP_KINDS = ("tool", "model", "decision", "gate")
MAX_SUMMARY = 160
GAPS = 0   # agent_step rows that could not be written since start (N6)


def _short(s: str) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= MAX_SUMMARY else s[: MAX_SUMMARY - 3] + "..."


def _write(run_id: str, visit_id: str | None, payload: dict[str, Any]) -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO audit_log (kind, actor, auth, visit_id, run_id, payload) "
                     "VALUES ('agent_step', 'agent', 'service', %s, %s, %s)", (visit_id, run_id, Jsonb(payload)))


async def write(run_id: str, visit_id: str | None, step_kind: str, name: str, args_summary: str = "-",
                result_summary: str = "-", *, server: str | None = None, latency_ms: float | None = None,
                tokens_in: int | None = None, tokens_out: int | None = None, cost_usd: float | None = None,
                cited_ids: list[str] | None = None, **extra: Any) -> None:
    """Write one agent_step row. A failure to audit is retried once, then logged loudly and counted (N6: the count
    is in /healthz as `trace_gaps`, so a gap in a trace is visible), but never stops the run: the proposal (the
    safety-relevant output) must still be created, and it has its own audit trail in the proposals table."""
    assert step_kind in STEP_KINDS, step_kind
    payload = {"step_kind": step_kind, "server": server, "name": name, "args_summary": _short(args_summary),
               "result_summary": _short(result_summary), "latency_ms": latency_ms, "tokens_in": tokens_in,
               "tokens_out": tokens_out, "cost_usd": cost_usd, "cited_ids": list(cited_ids or []), **extra}
    global GAPS
    for attempt in range(2):
        try:
            await asyncio.to_thread(_write, run_id, visit_id, payload)
            return
        except Exception:  # noqa: BLE001
            if attempt == 0:
                await asyncio.sleep(0.2)
    GAPS += 1
    log.error("agent_step %s of run %s not audited (trace gap %d)", name, run_id, GAPS)
