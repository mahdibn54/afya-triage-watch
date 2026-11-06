// Types of the API (docs/api.md), taken from src/api/types.ts, which `npm run gen:api` generates from FastAPI's
// /openapi.json (E7-10). Do not hand-write shapes here: add an alias, or a narrower name for a field the API types
// as a plain string. Fields the API may leave null are optional (`?: X | null`) in the generated types.
import type { components } from "@/api/types";

type S = components["schemas"];

export type Colour = S["ProposalOut"]["proposed_colour"];
export type Role = S["UserOut"]["role"];
export type NoticeCode = S["Notice"]["code"];
export type Notice = S["Notice"];

export type User = S["UserOut"];
export type Me = S["MeOut"];

export type Queue = S["Queue"];
export type QueuePatient = S["QueuePatient"];

export type VitalsRequest = S["VitalsIn"];
export type VitalsResponse = S["VitalsOut"];
export type RemeasureProblem = S["Problem"];
/** The scored and shown inputs (docs/api.md section 3); the API names them as plain strings in a few places. */
export type VitalInput = "resp_rate" | "heart_rate" | "systolic_bp" | "temperature" | "spo2" | "mobility" | "consciousness" | "trauma";
export type Mobility = NonNullable<S["VitalsIn"]["mobility"]>;
export type Consciousness = NonNullable<S["VitalsIn"]["consciousness"]>;

export type Proposal = S["ProposalOut"];
export type EvidenceRow = S["EvidenceRow"];
export type Sign = S["Sign"];
export type ApproveRequest = S["ApproveIn"];
export type ApproveResponse = S["ApproveOut"];

export type ApiErrorBody = S["ErrorBody"];
export type AuditRow = S["AuditRowOut"];

export type Timeline = S["Timeline"];
export type TimelineReading = S["Reading"];
export type TimelineValue = S["Value"];
export type TraceStep = S["TraceStep"];
export type Gate = S["Gate"];
export type GateName = Gate["gate"];
