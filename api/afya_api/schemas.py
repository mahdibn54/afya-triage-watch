"""Pydantic models of docs/api.md for the endpoints of E6-1b, E6-3, E6-5, E6-6 (B regenerates web/src/api/types.ts
from /openapi.json). Field names are the ones in the document."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Colour = Literal["RED", "ORANGE", "YELLOW", "GREEN"]
NoticeCode = Literal["remeasure", "no_chart", "not_reviewed", "instruction_like_text", "vitals_due",
                     "clinician_reminded", "model_unavailable", "fhir_unavailable", "data_incomplete",
                     "agent_failed", "command_abandoned"]
Num = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class Notice(BaseModel):
    code: NoticeCode
    notification_id: str | None = None
    at: str | None = None


# ---------- vitals ----------

class VitalsIn(BaseModel):
    """api.md section 3 and 5. Every input is optional, at least one must be present (checked by the tool).
    Limits (plausibility) are NOT validation errors: an impossible value answers 200 with status remeasure."""
    model_config = ConfigDict(extra="forbid")
    visit_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,64}$")
    resp_rate: Num | None = None
    heart_rate: Num | None = None
    systolic_bp: Num | None = None
    temperature: Num | None = None
    spo2: Num | None = None
    mobility: Literal["walking", "with_help", "stretcher"] | None = None
    consciousness: Literal["alert", "confused", "voice", "pain", "unresponsive"] | None = None
    trauma: Literal["yes", "no"] | None = None
    complaint: str | None = Field(default=None, max_length=500)
    reported_worsening: bool = False   # the patient or the nurse reports the patient is worse (trigger nurse_reported)


class Problem(BaseModel):
    name: str
    value: float
    min: float
    max: float


class VitalsOut(BaseModel):
    status: Literal["saved", "remeasure"]
    observation_id: str | None = None     # saved: "Observation/<id>"
    run_id: str | None = None             # saved: "<visit_id>:<bare id>"
    problems: list[Problem] | None = None  # remeasure


# ---------- proposals ----------

class EvidenceSide(BaseModel):
    obs_id: str
    value: Any
    points: int | None = None


class EvidenceRow(BaseModel):
    input: str
    unit: str | None = None
    before: EvidenceSide
    after: EvidenceSide
    band_changed: bool


class QuoteSpan(BaseModel):
    start: int
    end: int


class Sign(BaseModel):
    code: str
    gloss: str
    colour: Colour
    source: Literal["complaint", "reading"]
    status: Literal["current", "other"]
    quote: str | None = None
    quote_span: QuoteSpan | None = None
    reason: str | None = None


class ProposalOut(BaseModel):
    id: str
    visit_id: str
    patient_label: str | None = None
    trigger: str
    status: Literal["pending", "approved", "rejected", "superseded"]
    reviewed: bool
    created_at: str
    age_minutes: int
    reminder_due: bool
    decided_by: str | None = None
    decided_at: str | None = None
    obs_id: str
    current_colour: Colour | None = None
    proposed_colour: Colour
    tews_before: int | None = None
    tews_after: int | None = None
    reasons: list[str] = []
    evidence: list[EvidenceRow] = []
    agent_action: Literal["propose", "propose_and_remeasure", "request_missing_value"] | None = None
    missing_input: str | None = None
    complaint: str | None = None
    signs_verdict: Literal["found", "none", "unsure"] | None = None
    signs: list[Sign] = []
    rationale: str | None = None
    rationale_source: Literal["model", "code"] | None = None
    notices: list[Notice] = []


class ApproveIn(BaseModel):
    """colour: the colour the nurse confirms (normally the proposed one, any level is allowed); if it differs from
    the proposed colour, override_reason is required (422)."""
    model_config = ConfigDict(extra="forbid")
    colour: Colour
    signs_kept: list[str] = []
    override_reason: str | None = Field(default=None, max_length=300)


class ApproveOut(BaseModel):
    proposal_id: str
    command_id: str
    status: Literal["approved"]


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=300)


class RejectOut(BaseModel):
    proposal_id: str
    status: Literal["rejected"]


class AcknowledgedProposal(BaseModel):
    proposal_id: str
    reviewed: Literal[True]


class AcknowledgedNotification(BaseModel):
    notification_id: str
    acknowledged: Literal[True]


# ---------- timeline, trace, gates ----------

class Value(BaseModel):
    value: Any
    unit: str | None = None
    points: int | None = None


class Reading(BaseModel):
    obs_id: str
    at: str | None = None
    values: dict[str, Value]
    tews: int | None = None
    colour: Colour | None = None
    complete: bool
    missing: list[str]
    signs: list[str]


class Timeline(BaseModel):
    visit_id: str
    chart_id: str | None = None
    readings: list[Reading]


class TraceStep(BaseModel):
    step: int
    at: str
    kind: Literal["tool", "model", "decision", "gate"]
    server: Literal["ours", "borrowed"] | None = None
    name: str
    args_summary: str
    result_summary: str
    latency_ms: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    provider: str | None = None
    served_by: str | None = None
    cited_ids: list[str] = []


class Refusal(BaseModel):
    by: str
    role: str | None = None
    at: str


class Gate(BaseModel):
    gate: Literal["proposed", "paused", "confirmed", "claimed", "written", "audited"]
    at: str | None = None
    by: str | None = None
    refused: list[Refusal] = []


# ---------- demo ----------

class DemoScenarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["p014"] = "p014"


class DemoVisitOut(BaseModel):
    visit_id: str


class DemoNextOut(BaseModel):
    obs_id: str


# ---------- session and read endpoints (E6-1a, E6-2) ----------

class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=1, max_length=64)


class UserOut(BaseModel):
    id: str
    name: str
    role: Literal["nurse", "clinician", "manager"]


class MeOut(UserOut):
    demo: bool


class LastReading(BaseModel):
    observation_id: str
    effective: str | None = None
    tews: int | None = None
    colour: Colour | None = None


class Recheck(BaseModel):
    rule: str
    interval_minutes: int | None = None
    due_at: str | None = None
    overdue: bool
    overdue_minutes: int | None = None


class QueuePatient(BaseModel):
    """api.md section 5. Fields are null when the record lacks the data (the patient then has data_incomplete)."""
    visit_id: str
    patient_id: str | None = None
    patient_label: str | None = None
    patient_name: str | None = None    # made-up (synthetic) full name, screens only; null for older patients
    file_number: str | None = None     # made-up "F-0000" file number, screens only
    confirmed_colour: Colour | None = None
    arrived_at: str | None = None
    minutes_waited: int | None = None
    target_minutes: int | None = None
    over_target_minutes: int | None = None
    over_target: bool
    last_reading: LastReading | None = None
    recheck: Recheck | None = None
    pending_proposals: int
    flags: list[Literal["second_look"]] = []
    notices: list[Notice] = []


class Queue(BaseModel):
    as_of: str
    site_rule_source: str | None = None
    truncated: bool
    notices: list[Notice] = []
    patients: list[QueuePatient]


class AuditRowOut(BaseModel):
    id: int
    at: str
    kind: str
    actor: str
    auth: str | None = None
    visit_id: str | None = None
    run_id: str | None = None
    payload: dict[str, Any]
