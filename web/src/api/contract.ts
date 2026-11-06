// Types for the API contract in docs/api.md (E0-5).
// The FastAPI app has no response models yet, so `npm run gen:api` (openapi-typescript) only produces
// src/api/types.ts for the endpoints that exist. Until E6-1 ships, these hand-written types follow the
// contract field for field; E7-10 swaps them for the generated ones.

export type Colour = "RED" | "ORANGE" | "YELLOW" | "GREEN";
export type Role = "nurse" | "clinician" | "manager";

export type NoticeCode =
  | "remeasure"
  | "no_chart"
  | "not_reviewed"
  | "instruction_like_text"
  | "vitals_due"
  | "clinician_reminded"
  | "model_unavailable"
  | "fhir_unavailable"
  | "data_incomplete";

export interface Notice {
  code: NoticeCode;
  notification_id?: string;
  at?: string;
}

export interface User {
  id: string;
  name: string;
  role: Role;
}

export interface Me extends User {
  demo: boolean;
}

export interface QueuePatient {
  visit_id: string;
  patient_id: string;
  patient_label: string;
  confirmed_colour: Colour | null;
  arrived_at: string;
  minutes_waited: number;
  target_minutes: number | null;
  over_target_minutes: number | null;
  over_target: boolean;
  last_reading: { observation_id: string; effective: string; tews: number; colour: Colour } | null;
  recheck: {
    rule: string;
    interval_minutes: number;
    due_at: string;
    overdue: boolean;
    overdue_minutes: number;
  } | null;
  pending_proposals: number;
  flags: "second_look"[];
  notices: Notice[];
}

export interface Queue {
  as_of: string;
  site_rule_source: string;
  truncated: boolean;
  notices: Notice[];
  patients: QueuePatient[];
}

export type VitalInput =
  | "resp_rate"
  | "heart_rate"
  | "systolic_bp"
  | "temperature"
  | "spo2"
  | "mobility"
  | "consciousness"
  | "trauma";

export type Mobility = "walking" | "with_help" | "stretcher";
export type Consciousness = "alert" | "confused" | "voice" | "pain" | "unresponsive";

export interface VitalsRequest {
  visit_id: string;
  idempotency_key: string;
  resp_rate?: number;
  heart_rate?: number;
  systolic_bp?: number;
  temperature?: number;
  spo2?: number;
  mobility?: Mobility;
  consciousness?: Consciousness;
  trauma?: "yes" | "no";
  complaint?: string;
  /** The patient (or the nurse) reports that the patient is worse: a second look even without a score rise. */
  reported_worsening?: boolean;
}

export interface RemeasureProblem {
  name: VitalInput;
  value: number;
  min: number;
  max: number;
}

export type VitalsResponse =
  | { status: "saved"; observation_id: string; run_id: string }
  | { status: "remeasure"; problems: RemeasureProblem[] };

export interface EvidenceRow {
  input: VitalInput;
  unit: string | null;
  before: { obs_id: string; value: number | string; points: number | null };
  after: { obs_id: string; value: number | string; points: number | null };
  band_changed: boolean;
}

export interface Sign {
  code: string;
  gloss: string;
  colour: Colour;
  source: "complaint" | "reading";
  status: "current" | "other";
  quote: string | null;
  quote_span: { start: number; end: number } | null;
  reason: string | null;
}

export interface Proposal {
  id: string;
  visit_id: string;
  patient_label: string | null;
  trigger: string;
  status: "pending" | "approved" | "rejected" | "superseded";
  reviewed: boolean;
  created_at: string;
  age_minutes: number;
  reminder_due: boolean;
  decided_by: string | null;
  decided_at: string | null;
  obs_id: string;
  current_colour: Colour | null;
  proposed_colour: Colour;
  tews_before: number | null;
  tews_after: number | null;
  reasons: string[];
  evidence: EvidenceRow[];
  agent_action: "propose" | "propose_and_remeasure" | "request_missing_value" | null;
  missing_input: VitalInput | null;
  complaint: string | null;
  signs_verdict: "found" | "none" | "unsure" | null;
  signs: Sign[];
  rationale: string | null;
  rationale_source: "model" | "code" | null;
  notices: Notice[];
  /** Not in docs/api.md: the run that made this proposal. The fake derives it from obs_id (Q8). */
  run_id?: string;
}

export interface ApproveRequest {
  colour: Colour;
  signs_kept: string[];
  override_reason: string | null;
}

export interface ApproveResponse {
  proposal_id: string;
  command_id: string;
  status: "approved";
}

export interface ApiErrorBody {
  error: { code: string; message: string; problems?: unknown[] };
}

export interface AuditRow {
  id: number;
  at: string;
  kind: string;
  actor: string;
  auth: string | null;
  visit_id: string | null;
  run_id: string | null;
  payload: Record<string, unknown>;
}

export interface TimelineValue {
  value: number | string;
  unit: string | null;
  points: number | null;
}

export interface TimelineReading {
  obs_id: string;
  at: string;
  values: Partial<Record<VitalInput, TimelineValue>>;
  tews: number | null;
  colour: Colour | null;
  complete: boolean;
  missing: VitalInput[];
  signs: string[];
}

export interface Timeline {
  visit_id: string;
  chart_id: string | null;
  readings: TimelineReading[];
}

export interface TraceStep {
  step: number;
  at: string;
  kind: "tool" | "model" | "decision" | "gate";
  server: "ours" | "borrowed" | null;
  name: string;
  args_summary: string;
  result_summary: string;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  cited_ids: string[];
}

export type GateName = "proposed" | "paused" | "confirmed" | "claimed" | "written" | "audited";

export interface Gate {
  gate: GateName;
  at: string | null;
  by: string | null;
  refused: { by: string; role: Role | null; at: string }[];
}
