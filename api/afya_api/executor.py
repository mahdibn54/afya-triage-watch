"""E6-3: run an approved command (E6-4 adds the startup sweep to this module).

`resume_after_approval` is the seam the LangGraph agent (E5) replaces: today it calls the executor directly
(afya-mcp act tool raise_recheck_flag, actor = the approving user); E5 will resume the paused graph with the
command id instead and the graph will call the same tool.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from afya_mcp import db

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
