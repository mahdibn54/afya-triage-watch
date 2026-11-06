"""E5-7: immediate RED/ORANGE notifications and the watch loop (architecture section 4).

- When a run creates a RED or ORANGE proposal, the clinician on duty is reminded at once (`notify_at_creation`).
- Every WATCH_INTERVAL_SECONDS (60; 30 in the demo) `watch_once` reads get_queue_state and, through afya-mcp
  `notify_staff` (actor 'agent', audited, fixed text):
    * vitals_due: a waiting patient whose site re-check interval has passed (site rule, not SATS), once per due time;
    * clinician_reminder: a pending proposal still unread after the site limit (ORANGE 5 min, RED 1 min), once.
Nothing in the queue changes: no proposal, command, colour or FHIR record is written here.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

from afya_mcp import db

from .mcp_client import Gateway

log = logging.getLogger("afya_api.watch")
URGENT = ("RED", "ORANGE")


async def notify_at_creation(ctx: Any, state: dict[str, Any], proposal: dict[str, Any]) -> None:
    """Agent hook, called once when a run creates a proposal: RED/ORANGE -> clinician_reminder now."""
    if proposal["payload"].get("to_colour") not in URGENT:
        return
    args = {"kind": "clinician_reminder", "actor": "agent", "proposal_id": str(proposal["id"]),
            "visit_id": ctx.visit_id, "run_id": ctx.run_id}
    try:
        await ctx.gateway.act("notify_staff", args)
    except Exception as e:  # noqa: BLE001 - a reminder never stops the run; the watch loop is the backstop
        log.warning("immediate reminder for proposal %s failed (%s)", proposal["id"], type(e).__name__)


def _sent_since(kind: str, column: str, value: str, since: str) -> bool:
    with db.connect() as conn:
        return conn.execute(f"SELECT 1 FROM notifications WHERE kind = %s AND {column} = %s AND at >= %s LIMIT 1",
                            (kind, value, since)).fetchone() is not None


def _reminders(proposal_ids: list[str]) -> dict[str, int]:
    """clinician_reminder notifications already sent, per proposal (one query for the whole pass)."""
    if not proposal_ids:
        return {}
    with db.connect() as conn:
        rows = conn.execute("SELECT proposal_id::text AS id, count(*) AS n FROM notifications "
                            "WHERE kind = 'clinician_reminder' AND proposal_id = ANY(%s::uuid[]) GROUP BY 1",
                            (proposal_ids,)).fetchall()
    return {r["id"]: r["n"] for r in rows}


async def watch_once(gateway: Gateway, site: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """One pass. Returns what was sent: {"vitals_due": [visit ids], "clinician_reminder": [proposal ids]}."""
    from afya_mcp import rules
    site = site if site is not None else rules.load_site()
    run_id = "watch:" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    queue = await gateway.read("get_queue_state", {"run_id": run_id})
    sent: dict[str, list[str]] = {"vitals_due": [], "clinician_reminder": []}
    for p in queue.get("patients", []):
        due = (p.get("recheck") or {}).get("due_at")
        if not (p.get("recheck") or {}).get("overdue") or not due:
            continue
        if await asyncio.to_thread(_sent_since, "vitals_due", "visit_id", p["visit_id"], due):
            continue
        out = await gateway.act("notify_staff", {"kind": "vitals_due", "visit_id": p["visit_id"], "actor": "agent",
                                                 "run_id": run_id})
        if out.get("status") == "sent":
            sent["vitals_due"].append(p["visit_id"])
    limits = site.get("clinician_reminder_after_minutes", {})
    due = [pr for pr in queue.get("proposals") or [] if pr.get("status") == "pending" and pr.get("reminder_due")
           and limits.get(pr.get("to_colour")) is not None]
    counts = await asyncio.to_thread(_reminders, [pr["proposal_id"] for pr in due])
    for pr in due:
        # one reminder at creation (RED/ORANGE) plus one from the watch loop once the limit has passed
        if counts.get(pr["proposal_id"], 0) >= 2:
            continue
        out = await gateway.act("notify_staff", {"kind": "clinician_reminder", "proposal_id": pr["proposal_id"],
                                                 "actor": "agent", "run_id": run_id})
        if out.get("status") == "sent":
            sent["clinician_reminder"].append(pr["proposal_id"])
    if sent["vitals_due"] or sent["clinician_reminder"]:
        log.info("watch: %s", sent)
    return sent


def interval_seconds() -> float:
    return float(os.environ.get("WATCH_INTERVAL_SECONDS", "60"))


async def watch_loop(gateway: Gateway, interval: float | None = None) -> None:
    """Runs until cancelled (api lifespan). A failed pass is logged and the next one runs on time."""
    interval = interval if interval is not None else interval_seconds()
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        try:
            await watch_once(gateway)
        except Exception as e:  # noqa: BLE001
            log.warning("watch pass failed (%s)", type(e).__name__)
