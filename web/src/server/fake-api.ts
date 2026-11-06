// In-memory fake of the Afya API (docs/api.md), used while FAKE_API=1 (E7-0 … E7-9).
// Built from the contract's own example JSON (src/api/fixtures, extracted from docs/api.md), with times
// shifted to "now" so countdowns move. It does NOT score readings: scores come only from rules.py in the
// real backend, so a reading the fake does not know from the scenario is stored unscored.
// Synthetic data only.
import "server-only";

import type {
  AuditRow,
  Colour,
  Gate,
  Notice,
  Proposal,
  Queue,
  QueuePatient,
  RemeasureProblem,
  Role,
  Timeline,
  TimelineReading,
  TraceStep,
  User,
  VitalInput,
} from "@/api/contract";
import auditFx from "@/api/fixtures/get-audit.json";
import usersFx from "@/api/fixtures/get-demo-users.json";
import proposalsFx from "@/api/fixtures/get-proposals.json";
import queueFx from "@/api/fixtures/get-queue.json";
import traceFx from "@/api/fixtures/get-runs-id-trace.json";
import timelineFx from "@/api/fixtures/get-visits-id-timeline.json";

export const FAKE_COOKIE = "afya_fake_session";

const TARGET: Record<Colour, number> = { RED: 0, ORANGE: 10, YELLOW: 60, GREEN: 240 };

// docs/api.md section 3 (rules/plausibility.yaml, provisional).
const LIMITS: Partial<Record<VitalInput, [number, number]>> = {
  resp_rate: [3, 70],
  heart_rate: [20, 250],
  systolic_bp: [40, 300],
  temperature: [30, 43],
  spo2: [50, 100],
};
const UNITS: Partial<Record<VitalInput, string>> = {
  resp_rate: "/min",
  heart_rate: "/min",
  systolic_bp: "mm[Hg]",
  temperature: "Cel",
  spo2: "%",
};
const ENUMS: Partial<Record<VitalInput, string[]>> = {
  mobility: ["walking", "with_help", "stretcher"],
  consciousness: ["alert", "confused", "voice", "pain", "unresponsive"],
  trauma: ["yes", "no"],
};

// Agent run timing for the scripted P-014 reading (seconds after the reading is saved).
const RUN_STEP_DELAYS = [0.6, 1.2, 3.4, 4.6, 5.6, 6.0];

interface VisitState {
  visit_id: string;
  patient_id: string;
  patient_label: string;
  confirmed_colour: Colour | null;
  arrived_at: number;
  chart: boolean;
  recheck_interval: number;
  last_vitals_at: number;
  flags: "second_look"[];
  notices: Notice[];
  readings: TimelineReading[];
}

interface RunState {
  run_id: string;
  visit_id: string;
  started_at: number;
  steps: TraceStep[]; // full script; revealed by time
  proposal: Proposal | null; // created when the decision step is reached
}

interface GateState {
  proposed: number;
  paused: number;
  confirmed: { at: number; by: string } | null;
  written: number | null; // executor finished
  refused: { by: string; role: Role; at: number }[];
}

interface State {
  visits: Map<string, VisitState>;
  proposals: Map<string, Proposal>;
  gates: Map<string, GateState>;
  runs: Map<string, RunState>;
  audit: AuditRow[];
  nextObs: number;
  nextAudit: number;
  idem: Map<string, { observation_id: string; run_id: string }>;
}

const g = globalThis as unknown as { __afyaFake?: State };

function iso(ms: number): string {
  return new Date(ms).toISOString().replace("Z", "+00:00");
}
function uuid(): string {
  return crypto.randomUUID();
}
function clone<T>(x: T): T {
  return structuredClone(x);
}

const FX_NOW = Date.parse(queueFx.as_of);
/** Fixture time → now-relative time (the fixtures are all "08:52 on the demo morning"). */
function shift(fxIso: string, now: number): number {
  return Date.parse(fxIso) - FX_NOW + now;
}
function shiftIso(fxIso: string, now: number): string {
  return iso(shift(fxIso, now));
}

function audit(s: State, row: Omit<AuditRow, "id" | "at" | "auth"> & { at?: number }): void {
  s.audit.unshift({
    id: s.nextAudit++,
    at: iso(row.at ?? Date.now()),
    auth: row.actor === "agent" || row.actor === "system" ? null : "demo_switcher",
    kind: row.kind,
    actor: row.actor,
    visit_id: row.visit_id,
    run_id: row.run_id,
    payload: row.payload,
  });
}

/** Extra synthetic patients so the board looks like a real morning. Not in the contract fixtures. */
function extraVisits(now: number): VisitState[] {
  const min = 60_000;
  const mk = (
    id: string,
    colour: Colour,
    arrivedAgo: number,
    interval: number,
    lastVitalsAgo: number,
    tews: number,
    obs: number,
  ): VisitState => ({
    visit_id: `v${id}`,
    patient_id: `p${id}`,
    patient_label: `P-${id}`,
    confirmed_colour: colour,
    arrived_at: now - arrivedAgo * min,
    chart: true,
    recheck_interval: interval,
    last_vitals_at: now - lastVitalsAgo * min,
    flags: [],
    notices: [],
    readings: [
      {
        obs_id: `Observation/${obs}`,
        at: iso(now - lastVitalsAgo * min),
        values: {},
        tews,
        colour,
        complete: true,
        missing: [],
        signs: [],
      },
    ],
  });
  return [
    mk("002", "GREEN", 95, 60, 40, 1, 1003),
    mk("009", "YELLOW", 38, 30, 20, 3, 1031),
    mk("016", "GREEN", 9, 60, 7, 0, 1061),
  ];
}

function scenarioV014(now: number, withSecondReading: boolean): VisitState {
  const qp = queueFx.patients.find((p) => p.visit_id === "v014")!;
  const readings = (timelineFx.readings as TimelineReading[])
    .slice(0, withSecondReading ? 2 : 1)
    .map((r) => ({ ...clone(r), at: shiftIso(r.at, now) }));
  return {
    visit_id: "v014",
    patient_id: "p014",
    patient_label: "P-014",
    confirmed_colour: "YELLOW",
    arrived_at: shift(qp.arrived_at, now),
    chart: true,
    recheck_interval: 30,
    last_vitals_at: Date.parse(readings[readings.length - 1].at),
    flags: [],
    notices: [],
    readings,
  };
}

function fromQueueFixture(id: string, now: number): VisitState {
  const qp = queueFx.patients.find((p) => p.visit_id === id)! as unknown as QueuePatient;
  const lr = qp.last_reading;
  return {
    visit_id: qp.visit_id,
    patient_id: qp.patient_id,
    patient_label: qp.patient_label,
    confirmed_colour: qp.confirmed_colour,
    arrived_at: shift(qp.arrived_at, now),
    chart: qp.target_minutes !== null || !qp.notices.some((n) => n.code === "no_chart"),
    recheck_interval: qp.recheck?.interval_minutes ?? 30,
    last_vitals_at: lr ? shift(lr.effective, now) : shift(qp.arrived_at, now),
    flags: [...qp.flags],
    notices: qp.notices.map((n) => ({ ...n, at: n.at ? shiftIso(n.at, now) : undefined })),
    readings: lr
      ? [
          {
            obs_id: lr.observation_id,
            at: shiftIso(lr.effective, now),
            values: {},
            tews: lr.tews,
            colour: lr.colour,
            complete: true,
            missing: [],
            signs: [],
          },
        ]
      : [],
  };
}

function p014Proposal(createdAt: number, runId: string): Proposal {
  const fx = clone(proposalsFx[0]) as unknown as Proposal;
  return {
    ...fx,
    id: uuid(),
    created_at: iso(createdAt),
    age_minutes: 0,
    status: "pending",
    run_id: runId,
  };
}

function p014Run(startedAt: number): RunState {
  const runId = "v014:1057";
  const steps = (traceFx as TraceStep[]).map((st, i) => ({
    ...st,
    at: iso(startedAt + RUN_STEP_DELAYS[i] * 1000),
  }));
  return { run_id: runId, visit_id: "v014", started_at: startedAt, steps, proposal: null };
}

/** The run that followed P-014's first reading: scored, no earlier reading, so no trigger (baseline only). */
function p014BaselineRun(readingAt: number): RunState {
  const at = (sec: number) => iso(readingAt + sec * 1000);
  return {
    run_id: "v014:1042",
    visit_id: "v014",
    started_at: readingAt,
    proposal: null,
    steps: [
      { step: 1, at: at(1), kind: "tool", server: "ours", name: "compute_tews", args_summary: "observation_id=Observation/1042", result_summary: "scored: TEWS 3, YELLOW", latency_ms: 35.1, tokens_in: null, tokens_out: null, cost_usd: null, cited_ids: ["Observation/1042"] },
      { step: 2, at: at(2), kind: "tool", server: "ours", name: "check_deterioration", args_summary: "visit_id=v014", result_summary: "no earlier reading: baseline only, no trigger", latency_ms: 48.7, tokens_in: null, tokens_out: null, cost_usd: null, cited_ids: ["Observation/1042"] },
    ],
  };
}

/** The demo morning: the contract fixtures, with P-014's reading already in and its proposal pending. */
function initialState(now = Date.now(), p014Phase: "fixtures" | "first_reading" = "fixtures"): State {
  const s: State = {
    visits: new Map(),
    proposals: new Map(),
    gates: new Map(),
    runs: new Map(),
    audit: [],
    nextObs: 1070,
    nextAudit: 500,
    idem: new Map(),
  };
  const visits = [
    scenarioV014(now, p014Phase === "fixtures"),
    fromQueueFixture("v007", now),
    fromQueueFixture("v021", now),
    ...extraVisits(now),
  ];
  for (const v of visits) s.visits.set(v.visit_id, v);
  const base = p014BaselineRun(Date.parse(s.visits.get("v014")!.readings[0].at));
  s.runs.set(base.run_id, base);

  // Earlier audit history from the fixtures that is not about P-014's proposal.
  if (p014Phase === "fixtures") {
    const run = p014Run(Date.parse(s.visits.get("v014")!.readings[1].at) + 2000);
    run.started_at = now - 70_000;
    run.steps = run.steps.map((st, i) => ({ ...st, at: iso(run.started_at + RUN_STEP_DELAYS[i] * 1000) }));
    s.runs.set(run.run_id, run);
    const p = p014Proposal(run.started_at + RUN_STEP_DELAYS[4] * 1000, run.run_id);
    p.age_minutes = 1;
    run.proposal = p;
    s.proposals.set(p.id, p);
    s.gates.set(p.id, {
      proposed: Date.parse(p.created_at),
      paused: Date.parse(p.created_at) + 1000,
      confirmed: null,
      written: null,
      refused: [],
    });
    seedAuditForRun(s, run, p);
  }
  // An older proposal for P-009 that a newer reading replaced before anyone read it (not_reviewed).
  const old: Proposal = {
    ...(clone(proposalsFx[0]) as unknown as Proposal),
    id: uuid(),
    visit_id: "v009",
    patient_label: "P-009",
    status: "superseded",
    reviewed: false,
    created_at: iso(now - 26 * 60_000),
    age_minutes: 26,
    obs_id: "Observation/1024",
    current_colour: "YELLOW",
    proposed_colour: "ORANGE",
    tews_before: 3,
    tews_after: 5,
    reasons: ["colour rise YELLOW -> ORANGE (TEWS 5)"],
    evidence: [],
    complaint: null,
    signs: [],
    signs_verdict: null,
    rationale: null,
    rationale_source: "code",
  };
  s.proposals.set(old.id, old);
  void auditFx; // the fixture's rows describe the end state of the P-014 flow; the fake writes its own as it goes
  return s;
}

function seedAuditForRun(s: State, run: RunState, p: Proposal): void {
  audit(s, {
    at: Date.parse(run.steps[0].at) - 500,
    kind: "vitals_recorded",
    actor: "nurse-a",
    visit_id: run.visit_id,
    run_id: run.run_id,
    payload: { obs_id: p.obs_id },
  });
  audit(s, {
    at: Date.parse(p.created_at),
    kind: "proposal_created",
    actor: "agent",
    visit_id: run.visit_id,
    run_id: run.run_id,
    payload: { proposal_id: p.id, obs_id: p.obs_id, to_colour: p.proposed_colour },
  });
}

function state(): State {
  if (!g.__afyaFake) g.__afyaFake = initialState();
  return g.__afyaFake;
}

/** Reveal agent-run steps whose time has come; create the proposal at the decision step. */
function advance(s: State, now: number): void {
  for (const run of s.runs.values()) {
    if (run.proposal) continue;
    const decision = run.steps.find((st) => st.kind === "decision");
    if (decision && Date.parse(decision.at) <= now) {
      const p = p014Proposal(Date.parse(decision.at), run.run_id);
      run.proposal = p;
      s.proposals.set(p.id, p);
      s.gates.set(p.id, {
        proposed: Date.parse(p.created_at),
        paused: Date.parse(p.created_at) + 1000,
        confirmed: null,
        written: null,
        refused: [],
      });
      audit(s, {
        at: Date.parse(p.created_at),
        kind: "proposal_created",
        actor: "agent",
        visit_id: run.visit_id,
        run_id: run.run_id,
        payload: { proposal_id: p.id, obs_id: p.obs_id, to_colour: p.proposed_colour },
      });
    }
  }
  // The fixed executor finishes ~1.2 s after a confirmation: Flag + Encounter.priority written.
  for (const [pid, gs] of s.gates) {
    if (gs.confirmed && gs.written === null && now - gs.confirmed.at >= 1200) {
      gs.written = gs.confirmed.at + 1200;
      const p = s.proposals.get(pid)!;
      const v = s.visits.get(p.visit_id)!;
      const colour = (p as Proposal & { _confirmed_colour?: Colour })._confirmed_colour ?? p.proposed_colour;
      v.confirmed_colour = colour;
      if (!v.flags.includes("second_look")) v.flags.push("second_look");
      audit(s, {
        at: gs.written,
        kind: "command_done",
        actor: gs.confirmed.by,
        visit_id: p.visit_id,
        run_id: null,
        payload: { proposal_id: pid, obs_id: p.obs_id, colour, attempts: 1 },
      });
    }
  }
  for (const p of s.proposals.values()) {
    p.age_minutes = Math.max(0, Math.floor((now - Date.parse(p.created_at)) / 60_000));
    p.reminder_due = p.status === "pending" && p.age_minutes >= 5;
  }
}

function queuePatient(s: State, v: VisitState, now: number): QueuePatient {
  const waited = Math.floor((now - v.arrived_at) / 60_000);
  const target = v.chart && v.confirmed_colour ? TARGET[v.confirmed_colour] : null;
  const over = target === null ? null : Math.max(0, waited - target);
  const due = v.last_vitals_at + v.recheck_interval * 60_000;
  const overdueMin = Math.max(0, Math.floor((now - due) / 60_000));
  const last = [...v.readings].reverse().find((r) => r.tews !== null) ?? null;
  const pending = [...s.proposals.values()].filter((p) => p.visit_id === v.visit_id && p.status === "pending");
  const notices = [...v.notices];
  for (const p of s.proposals.values()) {
    if (p.visit_id === v.visit_id && p.status === "superseded" && !p.reviewed) {
      notices.push({ code: "not_reviewed", notification_id: p.id });
    }
    if (p.visit_id === v.visit_id && p.status === "pending" && p.reminder_due) {
      notices.push({ code: "clinician_reminded", at: iso(Date.parse(p.created_at) + 5 * 60_000) });
    }
  }
  if (!v.chart && !notices.some((n) => n.code === "no_chart")) notices.push({ code: "no_chart" });
  return {
    visit_id: v.visit_id,
    patient_id: v.patient_id,
    patient_label: v.patient_label,
    confirmed_colour: v.confirmed_colour,
    arrived_at: iso(v.arrived_at),
    minutes_waited: waited,
    target_minutes: target,
    over_target_minutes: over,
    over_target: (over ?? 0) > 0,
    last_reading: last
      ? { observation_id: last.obs_id, effective: last.at, tews: last.tews!, colour: last.colour! }
      : null,
    recheck: {
      rule: "site rule",
      interval_minutes: v.recheck_interval,
      due_at: iso(due),
      overdue: now > due,
      overdue_minutes: overdueMin,
    },
    pending_proposals: pending.length,
    flags: [...v.flags],
    notices,
  };
}

// ---------------------------------------------------------------- HTTP layer

export interface FakeReq {
  method: string;
  path: string[];
  search: URLSearchParams;
  body: unknown;
  userId: string | null;
}
export interface FakeRes {
  status: number;
  body: unknown;
  setUser?: string | null;
}

const users = usersFx as User[];

function err(status: number, code: string, message: string, problems?: unknown[]): FakeRes {
  return { status, body: { error: { code, message, ...(problems ? { problems } : {}) } } };
}

const DEMO_MODE = process.env.DEMO_MODE !== "0";
/** FAKE_ALL_NOTICES=1 shows the notices no scripted step produces (model offline, instruction-like text). */
const ALL_NOTICES = process.env.FAKE_ALL_NOTICES === "1";

export function fakeHandle(req: FakeReq): FakeRes {
  const s = state();
  const now = Date.now();
  advance(s, now);
  const [a, b, c] = req.path;
  const route = `${req.method} /${req.path.join("/")}`;

  if (route === "GET /healthz") return { status: 200, body: { status: "ok" } };

  if (route === "GET /demo/users") {
    if (!DEMO_MODE) return err(404, "not_found", "demo mode is off");
    return { status: 200, body: users };
  }
  if (route === "POST /login-as") {
    const id = (req.body as { user_id?: string } | null)?.user_id;
    const u = users.find((x) => x.id === id);
    if (!DEMO_MODE || !u) return err(404, "not_found", "unknown user");
    audit(s, { kind: "login", actor: u.id, visit_id: null, run_id: null, payload: { role: u.role } });
    return { status: 200, body: u, setUser: u.id };
  }

  if (a === "demo" && !DEMO_MODE) return err(404, "not_found", "demo mode is off");

  const me = users.find((u) => u.id === req.userId);
  if (!me) return err(401, "unauthorized", "sign in first");

  if (route === "GET /me") return { status: 200, body: { ...me, demo: DEMO_MODE } };

  if (route === "GET /queue") {
    const q: Queue = {
      as_of: iso(now),
      site_rule_source: queueFx.site_rule_source,
      truncated: false,
      notices: ALL_NOTICES ? [{ code: "model_unavailable", at: iso(now) }] : [],
      patients: [...s.visits.values()]
        .sort((x, y) => x.arrived_at - y.arrived_at)
        .map((v) => queuePatient(s, v, now)),
    };
    return { status: 200, body: q };
  }

  if (route === "POST /vitals") return postVitals(s, me, req.body as Record<string, unknown>, now);

  if (route === "GET /proposals") {
    const st = req.search.get("status") ?? "pending";
    const list = [...s.proposals.values()]
      .filter((p) => (st === "all" ? true : st === "superseded" ? p.status === "superseded" && !p.reviewed : p.status === st))
      .sort((x, y) => Date.parse(y.created_at) - Date.parse(x.created_at));
    return { status: 200, body: list.map(publicProposal) };
  }

  if (a === "proposals" && b && req.method === "GET" && c === "gates") {
    const gs = s.gates.get(b);
    if (!gs) return err(404, "not_found", "unknown proposal");
    return { status: 200, body: gates(gs) };
  }
  if (a === "proposals" && b && req.method === "POST" && (c === "approve" || c === "reject")) {
    return decide(s, me, b, c, req.body as Record<string, unknown> | null, now);
  }
  if (a === "proposals" && b && req.method === "POST" && c === "acknowledge") {
    if (me.role === "manager") return err(403, "forbidden", "only a nurse or clinician can acknowledge");
    const p = s.proposals.get(b);
    if (!p || p.status !== "superseded" || p.reviewed) return err(409, "conflict", "proposal is not waiting for review");
    p.reviewed = true;
    audit(s, { kind: "proposal_acknowledged", actor: me.id, visit_id: p.visit_id, run_id: null, payload: { proposal_id: p.id } });
    return { status: 200, body: { proposal_id: p.id, reviewed: true } };
  }
  if (a === "notifications" && b && req.method === "POST" && c === "acknowledge") {
    if (me.role === "manager") return err(403, "forbidden", "only a nurse or clinician can acknowledge");
    for (const v of s.visits.values()) {
      const i = v.notices.findIndex((n) => n.notification_id === b);
      if (i >= 0) {
        v.notices.splice(i, 1);
        audit(s, { kind: "notification_acknowledged", actor: me.id, visit_id: v.visit_id, run_id: null, payload: { notification_id: b } });
        return { status: 200, body: { notification_id: b, acknowledged: true } };
      }
    }
    return err(404, "not_found", "unknown notification");
  }

  if (route === "GET /audit") {
    const visit = req.search.get("visit_id");
    const run = req.search.get("run_id");
    const kind = req.search.get("kind");
    const limit = Number(req.search.get("limit") ?? 100);
    const rows = s.audit
      .filter((r) => (!visit || r.visit_id === visit) && (!run || r.run_id === run) && (!kind || r.kind === kind))
      .slice(0, limit);
    return { status: 200, body: rows };
  }

  if (a === "visits" && b && c === "timeline" && req.method === "GET") {
    const v = s.visits.get(b);
    if (!v) return err(404, "not_found", "unknown visit");
    const t: Timeline = { visit_id: v.visit_id, chart_id: v.chart ? "sats_adult_2012" : null, readings: v.readings };
    return { status: 200, body: t };
  }

  if (a === "runs" && b && c === "trace" && req.method === "GET") {
    const run = s.runs.get(decodeURIComponent(b));
    if (!run) return err(404, "not_found", "unknown run");
    return { status: 200, body: run.steps.filter((st) => Date.parse(st.at) <= now) };
  }

  if (a === "demo") {
    if (!DEMO_MODE) return err(404, "not_found", "demo mode is off");
    if (route === "POST /demo/scenario") {
      g.__afyaFake = initialState(now, "first_reading");
      return { status: 200, body: { visit_id: "v014" } };
    }
    if (route === "POST /demo/scenario/next") {
      const v = s.visits.get("v014")!;
      if (v.readings.length >= 2) return err(409, "conflict", "the scenario has no more readings");
      return { status: 200, body: { obs_id: addScenarioReading(s, me, now) } };
    }
  }

  return err(404, "not_found", `no route ${route}`);
}

function addScenarioReading(s: State, me: User, now: number): string {
  const v = s.visits.get("v014")!;
  const r = clone((timelineFx.readings as TimelineReading[])[1]);
  r.at = iso(now);
  v.readings.push(r);
  v.last_vitals_at = now;
  const run = p014Run(now);
  s.runs.set(run.run_id, run);
  audit(s, { at: now, kind: "vitals_recorded", actor: me.id, visit_id: "v014", run_id: run.run_id, payload: { obs_id: r.obs_id } });
  return r.obs_id;
}

function postVitals(s: State, me: User, body: Record<string, unknown>, now: number): FakeRes {
  if (me.role === "manager") return err(403, "forbidden", "only a nurse or clinician can record vitals");
  const problems: { name: string; message: string }[] = [];
  const visitId = body.visit_id;
  const key = body.idempotency_key;
  if (typeof visitId !== "string" || !s.visits.has(visitId)) problems.push({ name: "visit_id", message: "unknown visit" });
  if (typeof key !== "string" || !/^[A-Za-z0-9._:-]{1,64}$/.test(key)) problems.push({ name: "idempotency_key", message: "1 to 64 characters" });
  const complaint = body.complaint;
  if (complaint !== undefined && complaint !== null && (typeof complaint !== "string" || Array.from(complaint).length > 500)) {
    problems.push({ name: "complaint", message: "at most 500 characters" });
  }
  if (body.reported_worsening !== undefined && typeof body.reported_worsening !== "boolean") {
    problems.push({ name: "reported_worsening", message: "true or false" });
  }
  const allowed = new Set(["visit_id", "idempotency_key", "complaint", "reported_worsening", ...Object.keys(UNITS), ...Object.keys(ENUMS)]);
  for (const k of Object.keys(body)) if (!allowed.has(k)) problems.push({ name: k, message: "unknown input" });
  const inputs = (Object.keys(UNITS) as VitalInput[]).concat(Object.keys(ENUMS) as VitalInput[]).filter((k) => body[k] !== undefined && body[k] !== null && body[k] !== "");
  if (inputs.length === 0) problems.push({ name: "inputs", message: "at least one value" });
  for (const k of inputs) {
    if (ENUMS[k] && !ENUMS[k]!.includes(String(body[k]))) problems.push({ name: k, message: "not an allowed value" });
    if (UNITS[k] && typeof body[k] !== "number") problems.push({ name: k, message: "must be a number" });
  }
  if (problems.length) return err(422, "invalid", "check the highlighted values", problems);

  const prior = s.idem.get(key as string);
  if (prior) return { status: 200, body: { status: "saved", ...prior } };

  const out: RemeasureProblem[] = [];
  for (const k of inputs) {
    const lim = LIMITS[k];
    const val = body[k] as number;
    if (lim && (val < lim[0] || val > lim[1])) out.push({ name: k, value: val, min: lim[0], max: lim[1] });
  }
  const v = s.visits.get(visitId as string)!;
  if (out.length) {
    const nid = uuid();
    v.notices.push({ code: "remeasure", notification_id: nid, at: iso(now) });
    audit(s, { at: now, kind: "vitals_refused", actor: me.id, visit_id: v.visit_id, run_id: null, payload: { inputs: out.map((p) => p.name) } });
    return { status: 200, body: { status: "remeasure", problems: out } };
  }

  // The scripted P-014 reading (same numbers as docs/api.md) starts the scripted agent run.
  const scripted = (timelineFx.readings as TimelineReading[])[1];
  const isScripted =
    v.visit_id === "v014" &&
    v.readings.length === 1 &&
    (Object.keys(scripted.values) as VitalInput[]).every((k) => String(scripted.values[k]!.value) === String(body[k]));
  let obsId: string;
  let runId: string;
  if (isScripted) {
    obsId = addScenarioReading(s, me, now);
    runId = "v014:1057";
  } else {
    const n = s.nextObs++;
    obsId = `Observation/${n}`;
    runId = `${v.visit_id}:${n}`;
    const values: TimelineReading["values"] = {};
    for (const k of inputs) values[k] = { value: body[k] as number | string, unit: UNITS[k] ?? null, points: null };
    v.readings.push({ obs_id: obsId, at: iso(now), values, tews: null, colour: null, complete: false, missing: [], signs: [] });
    v.last_vitals_at = now;
    v.notices = v.notices.filter((n) => n.code !== "vitals_due" && n.code !== "remeasure");
    audit(s, { at: now, kind: "vitals_recorded", actor: me.id, visit_id: v.visit_id, run_id: runId, payload: { obs_id: obsId } });
    if (body.reported_worsening === true) reportedWorsening(s, v, obsId, typeof complaint === "string" ? complaint : null, now);
  }
  s.idem.set(key as string, { observation_id: obsId, run_id: runId });
  return { status: 200, body: { status: "saved", observation_id: obsId, run_id: runId } };
}

/**
 * Patient-reported change (Deterioration Watch): like the real agent's `nurse_reported` trigger, a second look at
 * the confirmed colour even when the score did not rise. The fake never scores, so it never proposes a higher colour.
 */
function reportedWorsening(s: State, v: VisitState, obsId: string, complaint: string | null, now: number): void {
  if (!v.confirmed_colour) return;
  for (const old of s.proposals.values()) {
    if (old.visit_id === v.visit_id && old.status === "pending") old.status = "superseded";
  }
  const p: Proposal = {
    ...(clone(proposalsFx[0]) as unknown as Proposal),
    id: uuid(),
    visit_id: v.visit_id,
    patient_label: v.patient_label,
    trigger: "nurse_reported",
    status: "pending",
    reviewed: false,
    created_at: iso(now + 1000),
    age_minutes: 0,
    obs_id: obsId,
    current_colour: v.confirmed_colour,
    proposed_colour: v.confirmed_colour,
    tews_before: null,
    tews_after: null,
    reasons: ["nurse reported worsening"],
    evidence: [],
    agent_action: "propose",
    missing_input: null,
    complaint,
    signs: [],
    signs_verdict: complaint ? "none" : null,
    rationale: "The patient or the nurse reported that the patient feels worse. Please take a second look.",
    rationale_source: "code",
    notices: [],
  };
  s.proposals.set(p.id, p);
  s.gates.set(p.id, { proposed: now + 1000, paused: now + 1500, confirmed: null, written: null, refused: [] });
  audit(s, { at: now + 1000, kind: "proposal_created", actor: "agent", visit_id: v.visit_id, run_id: null, payload: { proposal_id: p.id, obs_id: obsId, to_colour: p.proposed_colour } });
}

function decide(s: State, me: User, pid: string, what: "approve" | "reject", body: Record<string, unknown> | null, now: number): FakeRes {
  const p = s.proposals.get(pid);
  if (me.role !== "nurse" && me.role !== "clinician") {
    const gs = s.gates.get(pid);
    gs?.refused.push({ by: me.id, role: me.role, at: now });
    audit(s, { at: now, kind: `${what}_refused`, actor: me.id, visit_id: null, run_id: null, payload: { proposal_id: pid, reason: "role" } });
    return err(403, "forbidden", `only a nurse or clinician can ${what}`);
  }
  if (!p || p.status !== "pending") {
    audit(s, { at: now, kind: `${what}_refused`, actor: me.id, visit_id: p?.visit_id ?? null, run_id: null, payload: { proposal_id: pid, reason: "not_pending" } });
    return err(409, "conflict", "proposal is not pending");
  }
  if (what === "reject") {
    const reason = typeof body?.reason === "string" ? body.reason.trim() : "";
    if (!reason) return err(422, "invalid", "a reason is required", [{ name: "reason", message: "required" }]);
    p.status = "rejected";
    p.decided_by = me.id;
    p.decided_at = iso(now);
    audit(s, { at: now, kind: "proposal_rejected", actor: me.id, visit_id: p.visit_id, run_id: null, payload: { proposal_id: pid, obs_id: p.obs_id } });
    return { status: 200, body: { proposal_id: pid, status: "rejected" } };
  }
  const colour = body?.colour as Colour | undefined;
  if (!colour || !(colour in TARGET)) return err(422, "invalid", "colour is required", [{ name: "colour", message: "required" }]);
  const override = typeof body?.override_reason === "string" ? body.override_reason.trim() : "";
  if (colour !== p.proposed_colour && !override) {
    return err(422, "invalid", "a reason is required when the colour differs from the proposal", [{ name: "override_reason", message: "required" }]);
  }
  const commandId = uuid();
  p.status = "approved";
  p.decided_by = me.id;
  p.decided_at = iso(now);
  (p as Proposal & { _confirmed_colour?: Colour })._confirmed_colour = colour;
  const gs = s.gates.get(pid)!;
  gs.confirmed = { at: now, by: me.id };
  audit(s, {
    at: now,
    kind: "proposal_approved",
    actor: me.id,
    visit_id: p.visit_id,
    run_id: null,
    payload: { proposal_id: pid, command_id: commandId, obs_id: p.obs_id, colour, signs_kept: body?.signs_kept ?? [], override: colour !== p.proposed_colour },
  });
  return { status: 200, body: { proposal_id: pid, command_id: commandId, status: "approved" } };
}

function gates(gs: GateState): Gate[] {
  const t = (ms: number | null | undefined) => (ms === null || ms === undefined ? null : iso(ms));
  const by = gs.confirmed?.by ?? null;
  return [
    { gate: "proposed", at: t(gs.proposed), by: "agent", refused: [] },
    { gate: "paused", at: t(gs.paused), by: null, refused: [] },
    {
      gate: "confirmed",
      at: t(gs.confirmed?.at),
      by,
      refused: gs.refused.map((r) => ({ ...r, at: iso(r.at) })),
    },
    { gate: "claimed", at: t(gs.confirmed?.at), by, refused: [] },
    { gate: "written", at: t(gs.written), by: gs.written ? by : null, refused: [] },
    { gate: "audited", at: t(gs.written), by: gs.written ? by : null, refused: [] },
  ];
}

function publicProposal(p: Proposal): Proposal {
  const { _confirmed_colour, ...rest } = p as Proposal & { _confirmed_colour?: Colour };
  void _confirmed_colour;
  if (ALL_NOTICES && rest.status === "pending") return { ...rest, notices: [...rest.notices, { code: "instruction_like_text" }] };
  return rest;
}
