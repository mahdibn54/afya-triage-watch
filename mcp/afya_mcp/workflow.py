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
import re
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

MAX_ATTEMPTS = 5
COLOURS = ("RED", "ORANGE", "YELLOW", "GREEN")
COMMAND_TTL = timedelta(hours=1)
APPROVER_ROLES = ("nurse", "clinician")
MAX_REASON = 300
RUN_ID = re.compile(r"^[A-Za-z0-9:_.-]{1,128}$")


class Forbidden(Exception):
    """The deciding user is not a nurse or clinician (HTTP 403)."""


class Conflict(Exception):
    """The proposal is not pending any more, or does not exist (HTTP 409)."""


class InvalidDecision(ValueError):
    """The decision itself is wrong: unknown colour, override without a reason, unknown sign code (HTTP 422)."""


def _audit(conn: psycopg.Connection, kind: str, actor: str, visit_id: str | None, payload: dict[str, Any],
           run_id: str | None = None) -> None:
    conn.execute("INSERT INTO audit_log (kind, actor, visit_id, run_id, payload) VALUES (%s, %s, %s, %s, %s)",
                 (kind, actor, visit_id, run_id, Jsonb(payload)))


def run_id_for(visit_id: str, obs_id: str) -> str:
    """api.md Q8: the agent run / LangGraph thread of one reading is "<visit_id>:<bare observation id>" (URL-safe)."""
    bare = lambda ref: [p for p in str(ref).split("/") if p][-1]  # noqa: E731
    run = f"{bare(visit_id)}:{bare(obs_id)}"
    if not RUN_ID.match(run):
        raise ValueError(f"cannot build a URL-safe run id from {visit_id!r} and {obs_id!r}")
    return run


def obs_ref(obs_id: str) -> str:
    """api.md Q9: Observation ids are always returned as "Observation/<id>", whether stored bare or as a reference."""
    return f"Observation/{[p for p in str(obs_id).split('/') if p][-1]}"


# ---------- E3-6: dedup key and insert ----------

def evidence_hash(obs_ids: Iterable[str], sign_codes: Iterable[str], rules_version: str) -> str:
    """sha256 over the sorted observation IDs, sorted sign codes and the rules version.

    Never include the model's quote text: a retry of the same run must hash the same. The inputs are code-validated
    IDs and allow-listed codes only. `rules_version` is the chart_id of the chart that scored the reading
    (for example "sats_adult_2012"): a chart change is a new chart_id, so no separate version field is needed.
    """
    body = {"obs": sorted(set(obs_ids)), "signs": sorted(set(sign_codes)), "rules": rules_version}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def insert_proposal(conn: psycopg.Connection, visit_id: str, trigger: str, obs_id: str, ehash: str,
                    payload: dict[str, Any]) -> dict[str, Any] | None:
    """payload must carry "to_colour" (RED/ORANGE/YELLOW/GREEN); approval copies it to the command. The other
    fields are the ones the approval card shows (see PAYLOAD_FIELDS and _check_payload); "cited_obs_ids" are the
    readings the executor lists on the Flag. Unknown or malformed fields are refused with ValueError before the
    INSERT. Returns the new proposal, or None when the same (visit, trigger, evidence) already exists (a retry)."""
    _check_payload(payload)
    return conn.execute(
        "INSERT INTO proposals (visit_id, trigger, evidence_hash, obs_id, payload) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (visit_id, trigger, evidence_hash) DO NOTHING RETURNING *",
        (visit_id, trigger, ehash, obs_id, Jsonb(payload))).fetchone()


NOTICE_CODES = ("remeasure", "no_chart", "not_reviewed", "instruction_like_text", "vitals_due", "clinician_reminded",
                "model_unavailable", "fhir_unavailable", "data_incomplete", "agent_failed")
# notifications.kind -> notice code of api.md section 6 (Q7: the database says clinician_reminder, the UI says
# clinician_reminded)
NOTICE_FROM_KIND = {"remeasure": "remeasure", "vitals_due": "vitals_due", "clinician_reminder": "clinician_reminded",
                    "model_unavailable": "model_unavailable", "agent_failed": "agent_failed"}


def notice_from_notification(n: dict[str, Any]) -> dict[str, Any]:
    """{code, notification_id, at} for one open notification row."""
    return {"code": NOTICE_FROM_KIND[n["kind"]], "notification_id": str(n["id"]), "at": n["at"].isoformat()}


AGENT_ACTIONS = ("propose", "propose_and_remeasure", "request_missing_value")
SIGNS_VERDICTS = ("found", "none", "unsure")
RATIONALE_SOURCES = ("model", "code")
SIGN_SOURCES = ("complaint", "reading")
SIGN_STATUSES = ("current", "other")
PAYLOAD_FIELDS = ("to_colour", "current_colour", "tews_before", "tews_after", "reasons", "evidence", "complaint",
                  "signs", "rationale", "notices", "agent_action", "missing_input", "signs_verdict",
                  "rationale_source", "cited_obs_ids")
MAX_COMPLAINT = 500
MAX_RATIONALE = 300
MAX_PAYLOAD_BYTES = 32_000


def _bad(field: str, why: str) -> ValueError:
    return ValueError(f"proposal payload[{field!r}] {why}")


def _str(payload: dict[str, Any], field: str, limit: int, nullable: bool = False) -> None:
    v = payload.get(field)
    if v is None and (nullable or field not in payload):
        return
    if not isinstance(v, str) or len(v) > limit:
        raise _bad(field, f"must be text of at most {limit} characters")


def _choice(payload: dict[str, Any], field: str, choices: tuple[str, ...], nullable: bool = True) -> None:
    v = payload.get(field)
    if field not in payload or (v is None and nullable):
        return
    if v not in choices:
        raise _bad(field, f"must be one of {choices}")


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_payload(payload: Any) -> None:
    """api.md section 6 / Q4 and Q13: exactly these field names, with these types. Unknown names are refused.
    Only to_colour is required; the agent fills the rest. Free text is limited (complaint 500, rationale 300)."""
    if not isinstance(payload, dict):
        raise ValueError("proposal payload must be an object")
    unknown = sorted(set(payload) - set(PAYLOAD_FIELDS))
    if unknown:
        raise ValueError(f"proposal payload has unknown field(s) {unknown}; allowed: {list(PAYLOAD_FIELDS)}")
    if payload.get("to_colour") not in COLOURS:
        raise ValueError(f"proposal payload['to_colour'] must be one of {COLOURS}, got {payload.get('to_colour')!r}")
    _choice(payload, "current_colour", COLOURS)
    for f in ("tews_before", "tews_after"):
        if payload.get(f) is not None and not _int(payload[f]):
            raise _bad(f, "must be an integer or null")
    _list_of_str(payload, "reasons", 300)
    _list_of_str(payload, "cited_obs_ids", 64, nonempty=True)
    _str(payload, "complaint", MAX_COMPLAINT)
    _str(payload, "rationale", MAX_RATIONALE)
    _str(payload, "missing_input", 64, nullable=True)
    _choice(payload, "agent_action", AGENT_ACTIONS, nullable=False)
    _choice(payload, "signs_verdict", SIGNS_VERDICTS)
    _choice(payload, "rationale_source", RATIONALE_SOURCES, nullable=False)
    _check_evidence(payload.get("evidence", []))
    _check_signs(payload.get("signs", []))
    notices = payload.get("notices", [])
    if not isinstance(notices, list) or not all(isinstance(n, dict) and n.get("code") in NOTICE_CODES for n in notices):
        raise _bad("notices", f"must be a list of objects whose code is one of {NOTICE_CODES}")
    if len(json.dumps(payload, default=str)) > MAX_PAYLOAD_BYTES:
        raise ValueError("proposal payload is too large")


def _list_of_str(payload: dict[str, Any], field: str, limit: int, nonempty: bool = False) -> None:
    v = payload.get(field, [])
    if not isinstance(v, list) or not all(isinstance(x, str) and len(x) <= limit and (x or not nonempty) for x in v):
        raise _bad(field, f"must be a list of text items of at most {limit} characters")


def _check_evidence(rows: Any) -> None:
    if not isinstance(rows, list):
        raise _bad("evidence", "must be a list")
    for r in rows:
        if not (isinstance(r, dict) and isinstance(r.get("input"), str) and isinstance(r.get("band_changed"), bool)
                and (r.get("unit") is None or isinstance(r["unit"], str))):
            raise _bad("evidence", "rows need input (text), unit (text or null), band_changed (true/false)")
        for side in ("before", "after"):
            s = r.get(side)
            if not (isinstance(s, dict) and isinstance(s.get("obs_id"), str) and "value" in s
                    and (s.get("points") is None or _int(s["points"]))):
                raise _bad("evidence", f"{side} needs obs_id, value and points")


def _check_signs(signs: Any) -> None:
    if not isinstance(signs, list):
        raise _bad("signs", "must be a list")
    for g in signs:
        span = g.get("quote_span") if isinstance(g, dict) else None
        ok = (isinstance(g, dict) and isinstance(g.get("code"), str) and isinstance(g.get("gloss"), str)
              and g.get("colour") in COLOURS and g.get("source") in SIGN_SOURCES and g.get("status") in SIGN_STATUSES
              and (g.get("quote") is None or isinstance(g["quote"], str))
              and (g.get("reason") is None or isinstance(g["reason"], str))
              and (span is None or (isinstance(span, dict) and _int(span.get("start")) and _int(span.get("end"))
                                    and 0 <= span["start"] <= span["end"])))
        if not ok:
            raise _bad("signs", "rows need code, gloss, colour, source, status, quote, quote_span {start,end}, reason")


def open_proposals(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Proposals nobody has decided yet (pending) and superseded ones nobody has reviewed, oldest first.
    Only IDs, codes and times: the payload's colour, never its text."""
    return conn.execute(
        "SELECT id, visit_id, trigger, obs_id, status, payload->>'to_colour' AS to_colour, created_at FROM proposals "
        "WHERE status = 'pending' OR (status = 'superseded' AND NOT reviewed) ORDER BY created_at").fetchall()


def list_proposals(conn: psycopg.Connection, status: str = "pending") -> list[dict[str, Any]]:
    """For GET /proposals: "pending" (default), "superseded" (not yet reviewed) or "all" (every proposal),
    oldest first, with the visit's patient label. A row without a to_colour is not a card (it could not be approved)
    and is left out."""
    where = {"pending": "p.status = 'pending'", "superseded": "p.status = 'superseded' AND NOT p.reviewed",
             "all": "true"}.get(status)
    if where is None:
        raise ValueError("status must be pending, superseded or all")
    return conn.execute(
        "SELECT p.*, v.patient_label, r.complaint AS reading_complaint FROM proposals p "
        "JOIN visits v ON v.id = p.visit_id "
        "LEFT JOIN readings r ON r.obs_id = regexp_replace(p.obs_id, '^.*/', '') "
        f"WHERE ({where}) AND p.payload ? 'to_colour' ORDER BY p.created_at").fetchall()


def open_notifications(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Notices nobody has dismissed yet (kind, visit, proposal, time), oldest first. Fixed-text notifications only."""
    return conn.execute("SELECT id, at, kind, visit_id, proposal_id FROM notifications "
                        "WHERE acknowledged_at IS NULL ORDER BY at").fetchall()


def acknowledge_notification(conn: psycopg.Connection, notification_id: str, user_id: str) -> bool:
    """Dismiss one notice (idempotent). False when it does not exist. Audited in the same transaction."""
    with conn.transaction():
        row = conn.execute("UPDATE notifications SET acknowledged_at = COALESCE(acknowledged_at, now()) "
                           "WHERE id = %s RETURNING id, visit_id, kind", (notification_id,)).fetchone()
        if row:
            _audit(conn, "notification_acknowledged", user_id, row["visit_id"],
                   {"notification_id": str(row["id"]), "kind": row["kind"]})
    return row is not None


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

def _require_decider(conn: psycopg.Connection, user_id: str, refused_kind: str, proposal_id: str, verb: str) -> None:
    """Role check shared by approve and reject: only a nurse or clinician decides. A refusal is audited."""
    role = conn.execute("SELECT role FROM users WHERE id = %s", (user_id,)).fetchone()
    if role is None or role["role"] not in APPROVER_ROLES:
        if role is not None:
            _audit(conn, refused_kind, user_id, None, {"proposal_id": str(proposal_id), "reason": "role"})
        raise Forbidden(f"only a nurse or clinician can {verb}")


def _clean_reason(reason: str | None) -> str | None:
    text = " ".join(reason.split()) if isinstance(reason, str) else ""
    if len(text) > MAX_REASON:
        raise InvalidDecision(f"the reason is limited to {MAX_REASON} characters")
    return text or None


def _check_decision(payload: dict[str, Any], colour: str | None, signs_kept: list[str] | None,
                    override_reason: str | None) -> dict[str, Any]:
    proposed = payload["to_colour"]
    confirmed = colour or proposed
    if confirmed not in COLOURS:
        raise InvalidDecision(f"colour must be one of {COLOURS}")
    reason = _clean_reason(override_reason)
    if confirmed != proposed and reason is None:
        raise InvalidDecision("override_reason is required when the confirmed colour differs from the proposed one")
    if signs_kept is not None:
        shown = {g["code"] for g in payload.get("signs", [])}
        if not all(isinstance(c, str) for c in signs_kept) or not set(signs_kept) <= shown:
            raise InvalidDecision("signs_kept must be sign codes shown on the proposal")
    out: dict[str, Any] = {"colour": confirmed, "proposed_colour": proposed}
    if confirmed != proposed:
        out["override_reason"] = reason
    if signs_kept is not None:
        out["signs_kept"] = sorted(set(signs_kept))
    return out


def approve_proposal(conn: psycopg.Connection, proposal_id: str, user_id: str, colour: str | None = None,
                     signs_kept: Iterable[str] | None = None, override_reason: str | None = None,
                     ttl: timedelta = COMMAND_TTL) -> dict[str, Any]:
    """Role check (Forbidden), single-use UPDATE (0 rows: Conflict), then decision + command + audit in ONE transaction.

    `colour` is the colour the nurse confirms (default: the proposed to_colour). It may be ANY level, lower than
    proposed included (api.md Q6), but a different colour needs a non-empty `override_reason` (InvalidDecision: the
    whole transaction rolls back, the proposal stays pending). The command's colour is the confirmed colour.
    `signs_kept` are the sign codes the nurse left ticked (must be codes the proposal shows). The audit row records
    the proposed and confirmed colour, the signs kept and the reason. The command takes obs_id, evidence_hash and
    visit_id from the proposal. Refusals are audited too ("Double approval click / manager approves: 409 / 403").
    """
    _require_decider(conn, user_id, "approve_refused", proposal_id, "approve")
    kept = None if signs_kept is None else list(signs_kept)
    try:
        with conn.transaction():
            p = conn.execute(
                "UPDATE proposals p SET status = 'approved', decided_by = %s, decided_at = now() "
                "FROM users u WHERE p.id = %s AND p.status = 'pending' AND u.id = %s "
                "AND u.role IN ('nurse', 'clinician') RETURNING p.*", (user_id, proposal_id, user_id)).fetchone()
            command = None
            if p is not None:
                decision = _check_decision(p["payload"], colour, kept, override_reason)   # raises: rolls back
                command = conn.execute(
                    "INSERT INTO commands (proposal_id, visit_id, obs_id, colour, evidence_hash, expires_at) "
                    "VALUES (%s, %s, %s, %s, %s, now() + %s) RETURNING *",
                    (p["id"], p["visit_id"], p["obs_id"], decision["colour"], p["evidence_hash"], ttl)).fetchone()
                _audit(conn, "proposal_approved", user_id, p["visit_id"],
                       {"proposal_id": str(p["id"]), "command_id": str(command["id"]), "obs_id": p["obs_id"],
                        **decision})
    except InvalidDecision:
        _audit(conn, "approve_refused", user_id, None, {"proposal_id": str(proposal_id), "reason": "invalid"})
        raise
    if p is None:
        _audit(conn, "approve_refused", user_id, None, {"proposal_id": str(proposal_id), "reason": "not pending"})
        raise Conflict("proposal is not pending")
    return {"proposal": p, "command": command}


def reject_proposal(conn: psycopg.Connection, proposal_id: str, user_id: str, reason: str) -> dict[str, Any]:
    """Same role check (Forbidden) and single-use UPDATE (Conflict) as approve. A reason is required
    (InvalidDecision). Decision and audit row are one transaction; no command is created, nothing reaches FHIR."""
    _require_decider(conn, user_id, "reject_refused", proposal_id, "reject")
    text = _clean_reason(reason)
    if text is None:
        raise InvalidDecision("a reason is required to reject a proposal")
    with conn.transaction():
        p = conn.execute(
            "UPDATE proposals p SET status = 'rejected', decided_by = %s, decided_at = now() "
            "FROM users u WHERE p.id = %s AND p.status = 'pending' AND u.id = %s AND u.role IN ('nurse', 'clinician') "
            "RETURNING p.*", (user_id, proposal_id, user_id)).fetchone()
        if p is not None:
            _audit(conn, "proposal_rejected", user_id, p["visit_id"],
                   {"proposal_id": str(p["id"]), "obs_id": p["obs_id"], "reason": text})
    if p is None:
        _audit(conn, "reject_refused", user_id, None, {"proposal_id": str(proposal_id), "reason": "not pending"})
        raise Conflict("proposal is not pending")
    return {"proposal": p}


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
