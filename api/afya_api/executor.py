"""E6-3 / E6-4: run an approved command and the startup sweep.

`resume_after_approval` is the seam the LangGraph agent (E5) replaces: today it calls the executor directly
(afya-mcp act tool raise_recheck_flag, actor = the approving user); E5 will resume the paused graph with the
command id instead and the graph will call the same tool.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from afya_mcp import db, workflow

from .deps import get_gateway
from .mcp_client import Gateway

log = logging.getLogger("afya_api.executor")


def _approver(command_id: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute("SELECT p.decided_by FROM commands c JOIN proposals p ON p.id = c.proposal_id "
                           "WHERE c.id = %s", (command_id,)).fetchone()
    return row["decided_by"] if row else None


async def resume_after_approval(command_id: str, actor: str | None = None,
                                gateway: Gateway | None = None) -> dict[str, Any]:
    """E6-3 (replaced by E5): execute the command. actor defaults to the user who approved it; the startup sweep passes
    'system'. Never raises: a failure leaves the command open and the sweep (or a retry) converges, because the
    executor is idempotent. Returns the tool's answer, or {"status": "failed", "reason": ...}."""
    gateway = gateway or get_gateway()
    who = actor or await asyncio.to_thread(_approver, command_id)
    if who is None:
        return {"status": "not_found", "command_id": command_id}
    try:
        out = await gateway.act("raise_recheck_flag", {"command_id": command_id, "actor": who})
    except Exception as e:  # noqa: BLE001
        log.warning("command %s not executed now (%s); the startup sweep will retry", command_id, type(e).__name__)
        return {"status": "failed", "command_id": command_id, "reason": type(e).__name__}
    if out.get("status") not in ("done", "already_done"):
        log.warning("command %s: %s (%s)", command_id, out.get("status"), out.get("reason"))
    return out


def _open_commands() -> list[str]:
    with db.connect() as conn:
        return [str(c["id"]) for c in workflow.sweep_open_commands(conn)]


async def sweep_on_startup(gateway: Gateway | None = None, attempts: int = 5,
                           delay: float = 3.0) -> list[dict[str, Any]]:
    """E6-4: resume every approved command that is not done (claimed ones resume, unclaimed ones are claimed while
    not expired), as actor 'system'. Idempotent: the executor is safe to run twice. If the database is not up yet
    it retries a few times, then gives up with a log line (the api still starts)."""
    for attempt in range(attempts):
        try:
            ids = await asyncio.to_thread(_open_commands)
            break
        except Exception as e:  # noqa: BLE001
            log.warning("startup sweep: database not ready (%s)", type(e).__name__)
            await asyncio.sleep(delay)
    else:
        return []
    results = [await resume_after_approval(cid, "system", gateway) for cid in ids]
    if ids:
        log.info("startup sweep: %d open command(s): %s", len(ids), [r.get("status") for r in results])
    return results
