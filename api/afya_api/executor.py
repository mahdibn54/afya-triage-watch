"""E6-3 / E6-4: run an approved command and the startup sweep.

After approval the paused LangGraph run (E5-2, agent.py) is resumed with the command id; its executor node calls
`run_command`, the fixed executor: afya-mcp act tool raise_recheck_flag with the approving user as actor. When no paused
run exists for the proposal (created outside a run, or the checkpoint is gone) or no agent is given, `run_command` is
called directly. Both paths are idempotent.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from afya_mcp import db, workflow

from .deps import get_gateway
from .mcp_client import Gateway

log = logging.getLogger("afya_api.executor")


class Resumer(Protocol):
    async def resume(self, command_id: str, actor: str) -> dict[str, Any]: ...


def _command(command_id: str) -> dict[str, Any] | None:
    """The approving user and the run of a command (S4: both go on every execution path)."""
    with db.connect() as conn:
        row = conn.execute("SELECT p.decided_by, p.visit_id, p.obs_id FROM commands c "
                           "JOIN proposals p ON p.id = c.proposal_id WHERE c.id = %s", (command_id,)).fetchone()
    if row is None:
        return None
    return {"decided_by": row["decided_by"], "run_id": workflow.run_id_for(row["visit_id"], row["obs_id"])}


async def run_command(gateway: Gateway, command_id: str, actor: str, run_id: str | None = None) -> dict[str, Any]:
    """The fixed executor: raise_recheck_flag(command_id) as `actor`, tagged with the run's id when there is one.
    Never raises: a failure leaves the command open and the sweep (or a retry) converges."""
    args = {"command_id": command_id, "actor": actor}
    if run_id:
        args["run_id"] = run_id
    try:
        out = await gateway.act("raise_recheck_flag", args)
    except Exception as e:  # noqa: BLE001
        why = str(getattr(e, "text", "") or type(e).__name__)[:160]   # afya-mcp's short error text, no record text
        hint = ("the visit or reading is not in the FHIR server (a reset?): it cannot succeed"
                if "NotFound" in why else "may be a passing outage")
        log.warning("command %s not executed now (%s; %s). Each startup sweep retries it until %d attempts are used, "
                    "then it is abandoned with a command_abandoned audit row", command_id, why, hint,
                    workflow.MAX_ATTEMPTS)
        return {"status": "failed", "command_id": command_id, "reason": type(e).__name__}
    if out.get("status") not in ("done", "already_done"):
        log.warning("command %s: %s (%s)", command_id, out.get("status"), out.get("reason"))
    return out


async def resume_after_approval(command_id: str, actor: str | None = None, gateway: Gateway | None = None,
                                agent: Resumer | None = None) -> dict[str, Any]:
    """E6-3: execute the command. actor defaults to the user who approved it (the startup sweep uses it too, S4: the
    Flag and the audit row name the person who decided, never `system`). With an agent the paused run is resumed
    (its executor node runs the command); without one the executor runs directly, tagged with the proposal's run id.
    Never raises. Returns the tool's answer, or {"status": "failed", "reason": ...}."""
    gateway = gateway or get_gateway()
    try:
        cmd = await asyncio.to_thread(_command, command_id)
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "command_id": command_id, "reason": type(e).__name__}
    if cmd is None:
        return {"status": "not_found", "command_id": command_id}
    who = actor or cmd["decided_by"]
    if agent is not None:
        try:
            return await agent.resume(command_id, who)
        except Exception as e:  # noqa: BLE001
            log.warning("resume of command %s failed (%s); executor runs directly", command_id, type(e).__name__)
    return await run_command(gateway, command_id, who, cmd["run_id"])


def _open_commands() -> list[str]:
    with db.connect() as conn:
        return [str(c["id"]) for c in workflow.sweep_open_commands(conn)]


async def sweep_on_startup(gateway: Gateway | None = None, attempts: int = 5, delay: float = 3.0,
                           agent: Resumer | None = None) -> list[dict[str, Any]]:
    """E6-4: resume every approved command that is not done (claimed ones resume, unclaimed ones are claimed while
    not expired), as the user who approved it, with the run id. Idempotent: the executor is safe to run twice. If
    the database is not up yet it retries a few times, then gives up with a log line (the api still starts)."""
    for attempt in range(attempts):
        try:
            ids = await asyncio.to_thread(_open_commands)
            break
        except Exception as e:  # noqa: BLE001
            log.warning("startup sweep: database not ready (%s)", type(e).__name__)
            await asyncio.sleep(delay)
    else:
        return []
    results = [await resume_after_approval(cid, None, gateway, agent) for cid in ids]
    if ids:
        log.info("startup sweep: %d open command(s): %s", len(ids), [r.get("status") for r in results])
    return results
