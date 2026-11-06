"""Proposal and command queries (E3-5, E3-6): the SQL of architecture Appendix A, one function per query.

Shared by afya-mcp (claim, mark done, resume for the executor) and the api (approve, startup sweep).
Every function takes an open psycopg connection (autocommit, see db.connect), so callers decide how it is
obtained; multi-statement operations open their own `conn.transaction()`.

How the api imports this: api/Dockerfile installs the `mcp/` package next to the api (build context is the repo
root), so `from afya_mcp.workflow import approve_proposal` works in both containers. Nothing here imports the MCP
SDK or FHIR code.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

MAX_ATTEMPTS = 5
COMMAND_TTL = timedelta(hours=1)
APPROVER_ROLES = ("nurse", "clinician")


class Forbidden(Exception):
    """The deciding user is not a nurse or clinician (HTTP 403)."""


class Conflict(Exception):
    """The proposal is not pending any more, or does not exist (HTTP 409)."""


def _audit(conn: psycopg.Connection, kind: str, actor: str, visit_id: str | None, payload: dict[str, Any],
           run_id: str | None = None) -> None:
    conn.execute("INSERT INTO audit_log (kind, actor, visit_id, run_id, payload) VALUES (%s, %s, %s, %s, %s)",
                 (kind, actor, visit_id, run_id, Jsonb(payload)))


# ---------- E3-6: dedup key and insert ----------

def evidence_hash(obs_ids: Iterable[str], sign_codes: Iterable[str], rules_version: str) -> str:
    """sha256 over the sorted observation IDs, sorted sign codes and the rules version.

    Never include the model's quote text: a retry of the same run must hash the same. The inputs are code-validated
    IDs and allow-listed codes only. `rules_version` identifies the chart used (for example its chart_id).
    """
    body = {"obs": sorted(set(obs_ids)), "signs": sorted(set(sign_codes)), "rules": rules_version}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def insert_proposal(conn: psycopg.Connection, visit_id: str, trigger: str, obs_id: str, ehash: str,
                    payload: dict[str, Any]) -> dict[str, Any] | None:
    """payload must carry "to_colour" (RED/ORANGE/YELLOW/GREEN); approval copies it to the command.
    Returns the new proposal, or None when the same (visit, trigger, evidence) already exists (a retry)."""
    return conn.execute(
        "INSERT INTO proposals (visit_id, trigger, evidence_hash, obs_id, payload) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (visit_id, trigger, evidence_hash) DO NOTHING RETURNING *",
        (visit_id, trigger, ehash, obs_id, Jsonb(payload))).fetchone()


def open_proposals(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Proposals nobody has decided yet (pending) and superseded ones nobody has reviewed, oldest first.
    Only IDs, codes and times: the payload's colour, never its text."""
    return conn.execute(
        "SELECT id, visit_id, trigger, obs_id, status, payload->>'to_colour' AS to_colour, created_at FROM proposals "
        "WHERE status = 'pending' OR (status = 'superseded' AND NOT reviewed) ORDER BY created_at").fetchall()


def supersede_pending(conn: psycopg.Connection, visit_id: str, latest_obs_id: str) -> int:
    """Newer vitals: pending proposals about an older reading become superseded, reviewed stays false."""
    return conn.execute(
        "UPDATE proposals SET status = 'superseded' WHERE visit_id = %s AND status = 'pending' AND obs_id <> %s",
        (visit_id, latest_obs_id)).rowcount


def acknowledge(conn: psycopg.Connection, proposal_id: str, user_id: str) -> bool:
    """A nurse has seen a superseded proposal: it stops showing as "not reviewed". Audited in the same transaction."""
    with conn.transaction():
        row = conn.execute("UPDATE proposals SET reviewed = true WHERE id = %s AND status = 'superseded' "
                           "AND NOT reviewed RETURNING visit_id", (proposal_id,)).fetchone()
        if row:
            _audit(conn, "proposal_acknowledged", user_id, row["visit_id"], {"proposal_id": str(proposal_id)})
    return row is not None


# ---------- E3-5: approve, claim, mark done, resume, sweep ----------

def approve_proposal(conn: psycopg.Connection, proposal_id: str, user_id: str,
                     ttl: timedelta = COMMAND_TTL) -> dict[str, Any]:
    """Role check (Forbidden), single-use UPDATE (0 rows: Conflict), then decision + command + audit in ONE transaction.

    The command takes obs_id, evidence_hash and visit_id from the proposal and its colour from payload["to_colour"].
    Refusals are audited too ("Double approval click / manager approves: 409 / 403, logged").
    """
    role = conn.execute("SELECT role FROM users WHERE id = %s", (user_id,)).fetchone()
    if role is None or role["role"] not in APPROVER_ROLES:
        if role is not None:
            _audit(conn, "approve_refused", user_id, None, {"proposal_id": str(proposal_id), "reason": "role"})
        raise Forbidden("only a nurse or clinician can approve")
    with conn.transaction():
        p = conn.execute(
            "UPDATE proposals p SET status = 'approved', decided_by = %s, decided_at = now() "
            "FROM users u WHERE p.id = %s AND p.status = 'pending' AND u.id = %s AND u.role IN ('nurse', 'clinician') "
            "RETURNING p.*", (user_id, proposal_id, user_id)).fetchone()
        if p is None:
            conflict = True
        else:
            conflict = False
            command = conn.execute(
                "INSERT INTO commands (proposal_id, visit_id, obs_id, colour, evidence_hash, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, now() + %s) RETURNING *",
                (p["id"], p["visit_id"], p["obs_id"], p["payload"]["to_colour"], p["evidence_hash"], ttl)).fetchone()
            _audit(conn, "proposal_approved", user_id, p["visit_id"],
                   {"proposal_id": str(p["id"]), "command_id": str(command["id"]), "obs_id": p["obs_id"]})
    if conflict:
        _audit(conn, "approve_refused", user_id, None, {"proposal_id": str(proposal_id), "reason": "not pending"})
        raise Conflict("proposal is not pending")
    return {"proposal": p, "command": command}


def claim_command(conn: psycopg.Connection, command_id: str) -> dict[str, Any] | None:
    """Unclaimed, not expired, still the latest reading and proposal approved: all inside the UPDATE.
    None means the claim failed (someone else holds it, it expired, or newer vitals arrived)."""
    return conn.execute(
        "UPDATE commands c SET claimed_at = now(), attempts = attempts + 1 "
        "FROM visits v WHERE c.id = %s AND c.claimed_at IS NULL AND c.expires_at > now() "
        "AND v.id = c.visit_id AND v.latest_obs_id = c.obs_id "
        "AND EXISTS (SELECT 1 FROM proposals p WHERE p.id = c.proposal_id AND p.status = 'approved') "
        "RETURNING c.*", (command_id,)).fetchone()


def resume_command(conn: psycopg.Connection, command_id: str) -> dict[str, Any] | None:
    """After a crash: claimed, not done, attempts < 5. A nurse-approved flag is still written when newer vitals
    arrived meanwhile (documented in Appendix A); the new reading gets its own run."""
    return conn.execute(
        "UPDATE commands SET attempts = attempts + 1 "
        "WHERE id = %s AND claimed_at IS NOT NULL AND done_at IS NULL AND attempts < %s RETURNING *",
        (command_id, MAX_ATTEMPTS)).fetchone()


def mark_done(conn: psycopg.Connection, command_id: str, actor: str = "agent",
              run_id: str | None = None) -> dict[str, Any] | None:
    """done_at and the audit row in one transaction. None if the command is not claimed or already done."""
    with conn.transaction():
        c = conn.execute("UPDATE commands SET done_at = now() WHERE id = %s AND claimed_at IS NOT NULL "
                         "AND done_at IS NULL RETURNING *", (command_id,)).fetchone()
        if c:
            _audit(conn, "command_done", actor, c["visit_id"],
                   {"command_id": str(c["id"]), "proposal_id": str(c["proposal_id"]), "obs_id": c["obs_id"],
                    "colour": c["colour"], "attempts": c["attempts"]}, run_id)
    return c


def sweep_open_commands(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Startup sweep: approved commands that are not done and may still run (attempts < 5). Claimed ones resume;
    unclaimed ones are claimable only while not expired. The caller runs claim_command or resume_command on each."""
    return conn.execute(
        "SELECT c.* FROM commands c JOIN proposals p ON p.id = c.proposal_id "
        "WHERE p.status = 'approved' AND c.done_at IS NULL AND c.attempts < %s "
        "AND (c.claimed_at IS NOT NULL OR c.expires_at > now()) ORDER BY c.expires_at",
        (MAX_ATTEMPTS,)).fetchall()
