"""E4-8: one afya.audit_log row per MCP tool call.

`call()` wraps a tool body: it checks the actor (act tools only), times the call, and writes kind = tool name, actor,
auth, visit_id, run_id and a payload with the trimmed inputs, the trimmed output (or the error), latency_ms and the
mount. Payloads never carry FHIR free text: tool outputs hold IDs, codes and numbers only, FHIR error diagnostics
are cut off, strings are capped and the whole payload is size-limited.

Actors: act tools take a user id from afya.users (the approving user for raise_recheck_flag, the nurse for
record_vitals, 'agent' or 'system' for automated calls); a manager or an unknown id is refused before the tool runs.
Read tools always log actor 'agent' (the model-facing tools have no actor field).

Audit failures are never silent: for an act tool the call fails (AuditFailed); for a read tool the error is logged
and the result is still returned (a read changes nothing).
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from .db import connect
from .fhir import FhirRejected, ref_id

log = logging.getLogger("afya_mcp.audit")

READ, ACT = "read", "act"
ACT_ROLES = ("nurse", "clinician", "agent", "system")
HUMAN_ROLES = ("nurse", "clinician", "manager")
MAX_STR = 120
MAX_ITEMS = 25
MAX_DEPTH = 6
MAX_BYTES = 8000


class AuditFailed(RuntimeError):
    """The audit row could not be written; an act tool must not report success without it."""


class ActorRefused(PermissionError):
    """The actor is unknown or may not run act tools (a manager reads only)."""


class Auditor(Protocol):
    def role(self, user_id: str) -> str | None: ...
    def write(self, kind: str, actor: str, auth: str, visit_id: str | None, run_id: str | None,
              payload: dict[str, Any]) -> None: ...


class PgAuditor:
    """Short-lived connection per call, like PgVisitStore (calls run in worker threads)."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url

    def role(self, user_id: str) -> str | None:
        with connect(self.url) as conn:
            row = conn.execute("SELECT role FROM users WHERE id = %s", (user_id,)).fetchone()
        return row["role"] if row else None

    def write(self, kind: str, actor: str, auth: str, visit_id: str | None, run_id: str | None,
              payload: dict[str, Any]) -> None:
        with connect(self.url) as conn:
            conn.execute("INSERT INTO audit_log (kind, actor, auth, visit_id, run_id, payload) "
                         "VALUES (%s, %s, %s, %s, %s, %s)", (kind, actor, auth, visit_id, run_id, Jsonb(payload)))


def call(auditor: Auditor | None, kind: str, mode: str, inputs: dict[str, Any], fn: Callable[[], Any],
         actor: str = "agent", run_id: str | None = None) -> Any:
    """Run `fn` and audit it. Blocking: call it from a worker thread."""
    run_id = _short(run_id, 128) if run_id else None
    if mode == ACT:
        if auditor is None:
            raise AuditFailed("audit log unavailable (no DATABASE_URL): act tools do not run without it")
        role = _role(auditor, actor)
        if role not in ACT_ROLES:
            _refuse(auditor, kind, actor, role, inputs, run_id)
            raise ActorRefused(f"actor {_short(str(actor), 64)!r} may not run {kind}")
        auth = "demo_switcher" if role in HUMAN_ROLES else "service"
    else:
        actor, auth = "agent", "service"

    start = time.perf_counter()
    result: Any = None
    error: BaseException | None = None
    try:
        result = fn()
    except Exception as e:  # audited below, then re-raised unchanged
        error = e
    latency_ms = round((time.perf_counter() - start) * 1000, 1)

    payload = {"mount": mode, "inputs": trim(inputs), "latency_ms": latency_ms,
               "output": None if error else trim(result), "error": error_text(error) if error else None}
    payload = _cap(payload)
    visit_id = _visit_of(inputs, result)
    if auditor is None:
        log.error("audit log unavailable: %s call not audited", kind)
    else:
        try:
            auditor.write(kind, actor, auth, visit_id, run_id, payload)
        except Exception as e:
            if mode == ACT:
                raise AuditFailed(f"{kind}: audit row not written ({type(e).__name__})") from (error or e)
            log.exception("audit row for read tool %s not written", kind)
    if error is not None:
        raise error
    return result


def _role(auditor: Auditor, actor: Any) -> str | None:
    if not isinstance(actor, str) or not actor:
        return None
    try:
        return auditor.role(actor)
    except Exception as e:
        raise AuditFailed(f"cannot check the actor ({type(e).__name__})") from e


def _refuse(auditor: Auditor, kind: str, actor: Any, role: str | None, inputs: dict[str, Any],
            run_id: str | None) -> None:
    """Refusals are audited too. An unknown actor cannot be the row's actor (foreign key): log it as 'system'."""
    known = role is not None
    payload = _cap({"mount": ACT, "inputs": trim(inputs), "output": None, "latency_ms": 0,
                    "error": "actor refused", "refused_actor": _short(str(actor), 64), "refused_role": role})
    try:
        auditor.write(f"{kind}_refused", actor if known else "system", "demo_switcher" if known else "service",
                      _visit_of(inputs, None), run_id, payload)
    except Exception as e:
        raise AuditFailed(f"{kind}: refusal not audited ({type(e).__name__})") from e


def _visit_of(inputs: dict[str, Any], result: Any) -> str | None:
    for source in (inputs, result if isinstance(result, dict) else {}):
        value = source.get("visit_id")
        if isinstance(value, str) and value:
            try:
                return _short(ref_id(value, "Encounter"), 128)
            except ValueError:
                return None
    return None


def error_text(e: BaseException) -> str:
    """Exception class and a short message. FHIR diagnostics (which could echo record text) are cut off."""
    msg = str(e)
    if isinstance(e, FhirRejected):
        m = re.match(r".*?HTTP \d+", msg)
        msg = m.group(0) if m else ""
    return _short(f"{type(e).__name__}: {msg}" if msg else type(e).__name__, 200)


def trim(value: Any, depth: int = 0) -> Any:
    """JSON-safe copy with capped strings, list lengths, key counts and depth."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _short(value, MAX_STR)
    if depth >= MAX_DEPTH:
        return "..."
    if isinstance(value, dict):
        items = list(value.items())
        out = {_short(str(k), 64): trim(v, depth + 1) for k, v in items[:MAX_ITEMS]}
        if len(items) > MAX_ITEMS:
            out["_more"] = len(items) - MAX_ITEMS
        return out
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        out_list = [trim(v, depth + 1) for v in seq[:MAX_ITEMS]]
        if len(seq) > MAX_ITEMS:
            out_list.append(f"... {len(seq) - MAX_ITEMS} more")
        return out_list
    return _short(str(value), MAX_STR)


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    """Whole-payload limit: an oversized output is replaced by its top-level keys."""
    if len(json.dumps(payload, default=str)) <= MAX_BYTES:
        return payload
    out = payload.get("output")
    payload = {**payload, "output": {"_trimmed": True,
                                     "keys": sorted(out)[:MAX_ITEMS] if isinstance(out, dict) else None}}
    if len(json.dumps(payload, default=str)) > MAX_BYTES:
        payload["inputs"] = {"_trimmed": True}
    return payload


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."
