"""E6-1a: GET /queue and GET /audit (docs/api.md sections 5 and 7). Any signed-in user, the manager included.

/queue reads afya-mcp's queue_state on the /ui mount: the same data as the agent's get_queue_state, but the screens'
polling is not written to the audit log as agent calls. /audit is a plain SELECT on afya.audit_log (afya_app may only
SELECT and INSERT it).
"""
from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query
from psycopg.rows import DictRow

from . import helpers
from .deps import User, current_user, get_conn, get_gateway
from .errors import ERROR_RESPONSES
from .mcp_client import Gateway
from .schemas import AuditRowOut, Queue

router = APIRouter(tags=["read"])

AUDIT_MAX = 500


@router.get("/queue", response_model=Queue, responses=ERROR_RESPONSES)
async def queue(_user: User = Depends(current_user), gateway: Gateway = Depends(get_gateway)) -> Queue:
    """Waiting patients in arrival order (the UI sorts by time left). If FHIR is down the patients are empty and the
    top-level notices say fhir_unavailable (200, not an error)."""
    try:
        out = await gateway.ui("queue_state", {})
    except Exception as e:
        raise helpers.tool_error(e) from e
    return Queue(as_of=out["as_of"], site_rule_source=out.get("site_rule_source"), truncated=out["truncated"],
                 notices=out.get("notices", []), patients=out["patients"])


@router.get("/audit", response_model=list[AuditRowOut], responses=ERROR_RESPONSES)
def audit(visit_id: str | None = Query(None, max_length=64), run_id: str | None = Query(None, max_length=128),
          kind: str | None = Query(None, max_length=64), limit: int = Query(100, ge=1, le=AUDIT_MAX),
          include_screen_reads: bool = Query(False),
          _user: User = Depends(current_user),
          conn: psycopg.Connection[DictRow] = Depends(get_conn)) -> list[AuditRowOut]:
    """Newest first. Payloads hold ids, codes and numbers only (written that way by the audit wrapper). Rows of the
    read-only screen tools (mode `ui`: visit_timeline, demo_visit, written on every screen refresh) are left out
    unless include_screen_reads=true or `kind` asks for one of them; they are still written, never deleted."""
    where, args = [], []
    if not include_screen_reads and not kind:
        where.append("COALESCE(payload->>'mount', '') <> 'ui'")
    for column, value in (("visit_id", visit_id), ("run_id", run_id), ("kind", kind)):
        if value:
            where.append(f"{column} = %s")
            args.append(value)
    sql = ("SELECT id, at, kind, actor, auth, visit_id, run_id, payload FROM audit_log"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT %s")
    rows: list[dict[str, Any]] = conn.execute(sql, [*args, limit]).fetchall()
    return [AuditRowOut(**{**r, "at": r["at"].isoformat()}) for r in rows]
