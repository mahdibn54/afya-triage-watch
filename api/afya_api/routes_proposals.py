"""E6-1b and E6-3: proposals list, approve, reject, acknowledge."""
from __future__ import annotations

from typing import Any, Literal

import psycopg
from afya_mcp import rules, workflow
from fastapi import APIRouter, Depends, Query

from . import helpers
from .deps import User, current_user, get_conn
from .errors import ERROR_RESPONSES, ApiError
from .schemas import (
    AcknowledgedNotification,
    AcknowledgedProposal,
    ApproveIn,
    ApproveOut,
    ProposalOut,
    RejectIn,
    RejectOut,
)

router = APIRouter(tags=["proposals"])


def _site() -> dict[str, Any]:
    return rules.load_site()


def proposal_out(row: dict[str, Any], notifications: list[dict[str, Any]], site: dict[str, Any]) -> ProposalOut:
    """One row of afya.proposals (payload fields of api.md section 6) as the card needs it."""
    p = row["payload"]
    age = int((helpers.now() - row["created_at"]).total_seconds() // 60)
    limit = site.get("clinician_reminder_after_minutes", {}).get(p["to_colour"])
    notices = [dict(n) for n in p.get("notices", [])]
    notices += [workflow.notice_from_notification(n) for n in notifications if n["proposal_id"] == row["id"]]
    if row["status"] == "superseded" and not row["reviewed"]:
        notices.append({"code": "not_reviewed"})
    return ProposalOut(
        id=str(row["id"]), visit_id=row["visit_id"], patient_label=row.get("patient_label"), trigger=row["trigger"],
        status=row["status"], reviewed=row["reviewed"], created_at=row["created_at"].isoformat(), age_minutes=age,
        reminder_due=row["status"] == "pending" and limit is not None and age >= limit,
        decided_by=row["decided_by"], decided_at=helpers.iso(row["decided_at"]),
        obs_id=workflow.obs_ref(row["obs_id"]), current_colour=p.get("current_colour"), proposed_colour=p["to_colour"],
        tews_before=p.get("tews_before"), tews_after=p.get("tews_after"), reasons=p.get("reasons", []),
        evidence=p.get("evidence", []), agent_action=p.get("agent_action"), missing_input=p.get("missing_input"),
        complaint=p.get("complaint") or row.get("reading_complaint"), signs_verdict=p.get("signs_verdict"),
        signs=p.get("signs", []), rationale=p.get("rationale"), rationale_source=p.get("rationale_source"),
        notices=notices)


@router.get("/proposals", response_model=list[ProposalOut], responses=ERROR_RESPONSES)
def get_proposals(status: Literal["pending", "superseded", "all"] = Query("pending"),
                  _user: User = Depends(current_user), conn: psycopg.Connection = Depends(get_conn)):
    """status=pending (default), superseded (not yet reviewed) or all. Oldest first."""
    site = _site()
    notifications = workflow.open_notifications(conn)
    return [proposal_out(r, notifications, site) for r in workflow.list_proposals(conn, status)]


@router.post("/proposals/{proposal_id}/approve", response_model=ApproveOut, responses=ERROR_RESPONSES)
def approve(proposal_id: str, body: ApproveIn, user: User = Depends(current_user),
            conn: psycopg.Connection = Depends(get_conn)) -> ApproveOut:
    """403 role, 409 not pending (or unknown), 422 override without a reason. Decision + audit + command are ONE
    transaction (workflow.approve_proposal)."""
    pid = helpers.uuid_or_conflict(proposal_id)
    try:
        out = workflow.approve_proposal(conn, pid, user.id, body.colour, body.signs_kept, body.override_reason)
    except workflow.Forbidden as e:
        raise ApiError(403, str(e)) from e
    except workflow.Conflict as e:
        raise ApiError(409, str(e)) from e
    except workflow.InvalidDecision as e:
        raise ApiError(422, str(e)) from e
    command_id = str(out["command"]["id"])
    return ApproveOut(proposal_id=pid, command_id=command_id, status="approved")


@router.post("/proposals/{proposal_id}/reject", response_model=RejectOut, responses=ERROR_RESPONSES)
def reject(proposal_id: str, body: RejectIn, user: User = Depends(current_user),
           conn: psycopg.Connection = Depends(get_conn)) -> RejectOut:
    """403 role, 409 not pending (or unknown), 422 no reason. Nothing reaches FHIR: no command is created."""
    pid = helpers.uuid_or_conflict(proposal_id)
    try:
        workflow.reject_proposal(conn, pid, user.id, body.reason)
    except workflow.Forbidden as e:
        raise ApiError(403, str(e)) from e
    except workflow.Conflict as e:
        raise ApiError(409, str(e)) from e
    except workflow.InvalidDecision as e:
        raise ApiError(422, str(e)) from e
    return RejectOut(proposal_id=pid, status="rejected")


def _require_role(conn: psycopg.Connection, user: User) -> None:
    row = conn.execute("SELECT role FROM users WHERE id = %s", (user.id,)).fetchone()
    if row is None or row["role"] not in workflow.APPROVER_ROLES:
        raise ApiError(403, "only a nurse or clinician can do this")


@router.post("/proposals/{proposal_id}/acknowledge", response_model=AcknowledgedProposal, responses=ERROR_RESPONSES)
def acknowledge_proposal(proposal_id: str, user: User = Depends(current_user),
                         conn: psycopg.Connection = Depends(get_conn)) -> AcknowledgedProposal:
    """A superseded proposal nobody reviewed stops showing as not_reviewed. 409 when it is not superseded or was
    already reviewed."""
    _require_role(conn, user)
    pid = helpers.uuid_or_conflict(proposal_id)
    if not workflow.acknowledge(conn, pid, user.id):
        raise ApiError(409, "proposal is not superseded, or already reviewed")
    return AcknowledgedProposal(proposal_id=pid, reviewed=True)


@router.post("/notifications/{notification_id}/acknowledge", response_model=AcknowledgedNotification,
             responses=ERROR_RESPONSES)
def acknowledge_notification(notification_id: str, user: User = Depends(current_user),
                             conn: psycopg.Connection = Depends(get_conn)) -> AcknowledgedNotification:
    """Dismiss one notice. 404 if unknown."""
    _require_role(conn, user)
    nid = helpers.uuid_or_404(notification_id, "notification")
    if not workflow.acknowledge_notification(conn, nid, user.id):
        raise ApiError(404, "notification not found")
    return AcknowledgedNotification(notification_id=nid, acknowledged=True)

