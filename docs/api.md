# API contract (E0-5)

**Status: agreed. Proposed by B, all open questions in section 9 accepted by M.** Section 9 records the answers. Until
then the UI is built against the example JSON in this file.

FastAPI on `api:8080`. The Next.js app calls `/api/...` and its proxy strips the `/api` prefix (so `/api/queue` reaches
`api:8080/queue`). JSON everywhere. The signed-in user always comes from the session cookie, never from a request body.

## 1. Conventions

| Topic | Rule |
|---|---|
| Times | ISO 8601 with an offset, for example `2026-11-06T08:50:00+00:00`. |
| IDs | `visit_id` is the bare FHIR Encounter id (`v014`). Observation ids are always the full reference (`Observation/1057`). `proposal_id`, `command_id`, `notification_id` are UUIDs. `run_id` is URL-safe (letters, digits, `:` `-` `_` `.`). |
| Colours | `RED` `ORANGE` `YELLOW` `GREEN`. The UI also shows a label and a shape (■ ▲ ● ○), never colour alone. |
| Roles | `nurse`, `clinician`, `manager`. A manager reads only. `agent` and `system` exist in the database but never sign in. |
| Auth | Everything except `/healthz` and `/login-as` needs the session cookie: `401` otherwise. |
| Errors | Always `{ "error": { "code": string, "message": string } }`. Codes: `unauthorized` 401, `forbidden` 403, `not_found` 404, `conflict` 409, `invalid` 422 (adds `problems[]`), `unavailable` 503. FastAPI's own validation errors are mapped to `invalid`. |
| Text | Quotes, complaints and rationale are plain text. Never `dangerouslySetInnerHTML`. |
| Offsets | `quote_span` is `{ start, end }`, half-open, counted in Unicode code points of the **original** `complaint` the card shows (not the NFKC, case-folded copy the sign check uses). The UI slices with `Array.from(complaint).slice(start, end).join("")`. |
| Fake JSON | The example blocks below are the UI's fixtures. Copy them to `web/` while the real endpoints are not ready. |

## 2. Endpoints

"Backend today" says what already exists in `mcp/afya_mcp/` or `db/schema.sql` (checked against the code on the day this was written).

| Method | Path | Who | Backend today |
|---|---|---|---|
| POST | `/login-as` | anyone, `DEMO_MODE=1` only | users table ready; session cookie is E6-2 (B) |
| GET | `/demo/users` | anyone, `DEMO_MODE=1` only | users table ready |
| GET | `/me` | signed in | users table ready |
| GET | `/queue` | signed in | partial: `services.get_queue_state`; patient label, last TEWS and flags missing (Q3) |
| POST | `/vitals` | nurse, clinician | partial: `services.record_vitals` ready; complaint and starting the agent run missing (Q1) |
| GET | `/proposals` | signed in | partial: `workflow.open_proposals` returns few fields; the card needs the payload (Q4, Q5) |
| POST | `/proposals/{id}/approve` | nurse, clinician | partial: `workflow.approve_proposal` ready; colour override and `signs_kept` missing (Q6) |
| POST | `/proposals/{id}/reject` | nurse, clinician | to build: no reject function yet (Q6) |
| POST | `/proposals/{id}/acknowledge` | nurse, clinician | ready: `workflow.acknowledge` |
| POST | `/notifications/{id}/acknowledge` | nurse, clinician | grant ready: `afya_app` may update `acknowledged_at` only |
| GET | `/audit` | signed in (manager too) | ready: SELECT on `audit_log` |
| GET | `/visits/{id}/timeline` | signed in | partial: `compute_tews` per reading; raw values come from FHIR (Q5) |
| GET | `/runs/{run_id}/trace` | signed in | to build (E6-5) from `audit_log` |
| GET | `/proposals/{id}/gates` | signed in | to build (E6-5); the data exists |
| POST | `/demo/scenario` | `DEMO_MODE=1` only | to build (E6-6) |
| POST | `/demo/scenario/next` | `DEMO_MODE=1` only | to build (E6-6) |

## 3. Vital-sign inputs

Used by `POST /vitals` (request) and the timeline. Every input is optional: a missing input is reported, never guessed.
At least one must be present. Limits are the provisional ones in `rules/plausibility.yaml` (to be reviewed with the nurse).

| Input | Type | Unit | Allowed |
|---|---|---|---|
| `resp_rate` | number | /min | 3 to 70 |
| `heart_rate` | number | /min | 20 to 250 |
| `systolic_bp` | number | mmHg | 40 to 300 |
| `temperature` | number | °C | 30 to 43 |
| `spo2` | number, shown not scored | % | 50 to 100 |
| `mobility` | string | | `walking` `with_help` `stretcher` |
| `consciousness` | string | | `alert` `confused` `voice` `pain` `unresponsive` |
| `trauma` | string | | `yes` `no` |

## 4. Auth

### The `current_user` seam (for E6-2, B)
Every protected router depends on one function, `afya_api.deps.current_user` (returns `deps.User { id, name, role }`).
Today it raises `501` ("demo session not available yet (E6-2)"); tests replace it with
`app.dependency_overrides[deps.current_user]`. E6-2 plugs in by replacing the body of that function (same name, same
module): read the signed session cookie, return the `User` (role from `afya.users`), raise `HTTPException(401)` when there
is no valid session. Routers use `user.id` as the audit actor and never read a user from a request body. The error
handlers in `afya_api/errors.py` already turn `HTTPException` into the error body of section 1.

### POST /login-as
Request `{ "user_id": "nurse-a" }`. Sets the session cookie. `404` when `DEMO_MODE` is off or the user is unknown.

<!-- example: POST /login-as response -->
```json
{ "id": "nurse-a", "name": "Nurse A.", "role": "nurse" }
```

### GET /demo/users
The people the "Sign in as…" switcher offers (no `agent` or `system`).

<!-- example: GET /demo/users -->
```json
[
  { "id": "nurse-a", "name": "Nurse A.", "role": "nurse" },
  { "id": "clin-m", "name": "Dr. M", "role": "clinician" },
  { "id": "mgr-k", "name": "Dir. K", "role": "manager" }
]
```

### GET /me

<!-- example: GET /me -->
```json
{ "id": "nurse-a", "name": "Nurse A.", "role": "nurse", "demo": true }
```

## 5. Waiting room and vitals

### GET /queue
`patients` is in arrival order (oldest first); the UI sorts by time left, which is `target_minutes - minutes_waited`.
`target_minutes` is the SATS time-to-be-seen target of the confirmed colour. `recheck` is a **site rule**, not SATS.
`confirmed_colour` is what a nurse last confirmed, never the agent's proposal. `null` target means no chart or no
confirmed colour. `flags` currently holds `second_look` (an active second-look Flag on the visit).
`notices` on a patient are open notices for that visit; the top-level `notices` are not tied to one visit.

<!-- example: GET /queue -->
```json
{
  "as_of": "2026-11-06T08:52:10+00:00",
  "site_rule_source": "provisional site rule, to review with nurse",
  "truncated": false,
  "notices": [],
  "patients": [
    {
      "visit_id": "v014",
      "patient_id": "p014",
      "patient_label": "P-014",
      "confirmed_colour": "YELLOW",
      "arrived_at": "2026-11-06T08:00:00+00:00",
      "minutes_waited": 52,
      "target_minutes": 60,
      "over_target_minutes": 0,
      "over_target": false,
      "last_reading": {
        "observation_id": "Observation/1057",
        "effective": "2026-11-06T08:50:00+00:00",
        "tews": 6,
        "colour": "ORANGE"
      },
      "recheck": {
        "rule": "site rule",
        "interval_minutes": 30,
        "due_at": "2026-11-06T09:20:00+00:00",
        "overdue": false,
        "overdue_minutes": 0
      },
      "pending_proposals": 1,
      "flags": [],
      "notices": []
    },
    {
      "visit_id": "v007",
      "patient_id": "p007",
      "patient_label": "P-007",
      "confirmed_colour": "ORANGE",
      "arrived_at": "2026-11-06T08:30:00+00:00",
      "minutes_waited": 22,
      "target_minutes": 10,
      "over_target_minutes": 12,
      "over_target": true,
      "last_reading": {
        "observation_id": "Observation/1049",
        "effective": "2026-11-06T08:35:00+00:00",
        "tews": 5,
        "colour": "ORANGE"
      },
      "recheck": {
        "rule": "site rule",
        "interval_minutes": 15,
        "due_at": "2026-11-06T08:50:00+00:00",
        "overdue": true,
        "overdue_minutes": 2
      },
      "pending_proposals": 0,
      "flags": ["second_look"],
      "notices": [
        { "code": "vitals_due", "notification_id": "0b6d2c1e-5f3a-4b7d-8e19-2a4c6d8f0b13", "at": "2026-11-06T08:50:30+00:00" }
      ]
    },
    {
      "visit_id": "v021",
      "patient_id": "p021",
      "patient_label": "P-021",
      "confirmed_colour": "YELLOW",
      "arrived_at": "2026-11-06T08:40:00+00:00",
      "minutes_waited": 12,
      "target_minutes": null,
      "over_target_minutes": null,
      "over_target": false,
      "last_reading": null,
      "recheck": {
        "rule": "site rule",
        "interval_minutes": 30,
        "due_at": "2026-11-06T09:10:00+00:00",
        "overdue": false,
        "overdue_minutes": 0
      },
      "pending_proposals": 0,
      "flags": [],
      "notices": [{ "code": "no_chart" }]
    }
  ]
}
```

### POST /vitals
Request: the inputs of section 3 (flat), plus `visit_id`, `idempotency_key` (1 to 64 characters: letters, digits and
`. _ : -`) and an optional free-text `complaint` (at most 500 characters, architecture Appendix B). The API finds the
patient from the visit.
Responses: `200 saved`, `200 remeasure` (an impossible value: nothing is saved or scored, the UI shows the
re-measure notice), `422 invalid` (unknown input, bad value, no value). A retry with the same key returns the same
`observation_id`. `run_id` (`<visit_id>:<bare observation id>`, Q8) identifies the agent run that follows a saved reading.
`403` for a manager (the refusal is audited), `404` unknown visit, `503` when the data service is down. The complaint is
stored in Postgres (`afya.readings`), NFKC-normalised, never in FHIR; a retry keeps the first text.

<!-- example: POST /vitals request -->
```json
{
  "visit_id": "v014",
  "idempotency_key": "3f2b8a1c-9d4e-4b7a-8c15-6e0f2a7d9b31",
  "resp_rate": 26,
  "heart_rate": 112,
  "systolic_bp": 120,
  "temperature": 38.6,
  "spo2": 93,
  "mobility": "walking",
  "consciousness": "alert",
  "trauma": "no",
  "complaint": "Short of breath since morning. My mother had chest pain last year."
}
```

<!-- example: POST /vitals response saved -->
```json
{ "status": "saved", "observation_id": "Observation/1057", "run_id": "v014:1057" }
```

<!-- example: POST /vitals response remeasure -->
```json
{
  "status": "remeasure",
  "problems": [{ "name": "heart_rate", "value": 400, "min": 20, "max": 250 }]
}
```

## 6. Proposals, decisions, notices

### GET /proposals?status=pending
`status` is `pending` (default), `superseded` (not yet reviewed) or `all`. One object per proposal. `current_colour` is
the confirmed colour; `proposed_colour` is never lower. `evidence` lists the readings behind the flag, one row per input
whose value changed, with the record id of each reading; `band_changed` is true when the input moved into a higher
score band (the UI emphasises those rows). `signs` has both the signs that count (`status: "current"`) and the mentions
that do not (`status: "other"`, shown greyed with `reason`). A sign with `source: "reading"` comes from the vitals
(for example reduced consciousness) and has no quote. `signs_verdict` is the sign mapper's verdict (`found`, `none`,
`unsure`; `null` when the model was down). `agent_action` is the investigate step's decision (`propose`,
`propose_and_remeasure`, `request_missing_value`; `missing_input` names the value asked for). `reasons` are built by
code from the trigger. `rationale` (at most 300 characters) is the model's text if it passed the wording filter
(`rationale_source: "model"`), otherwise a sentence built by code (`"code"`).

<!-- example: GET /proposals -->
```json
[
  {
    "id": "b1f0c3a2-7d4e-4f8a-9c21-5e6a0d3b8f14",
    "visit_id": "v014",
    "patient_label": "P-014",
    "trigger": "colour_rise",
    "status": "pending",
    "reviewed": false,
    "created_at": "2026-11-06T08:50:41+00:00",
    "age_minutes": 1,
    "reminder_due": false,
    "decided_by": null,
    "decided_at": null,
    "obs_id": "Observation/1057",
    "current_colour": "YELLOW",
    "proposed_colour": "ORANGE",
    "tews_before": 3,
    "tews_after": 6,
    "reasons": ["colour rise YELLOW -> ORANGE (TEWS 6)"],
    "evidence": [
      {
        "input": "resp_rate", "unit": "/min",
        "before": { "obs_id": "Observation/1042", "value": 22, "points": 2 },
        "after": { "obs_id": "Observation/1057", "value": 26, "points": 2 },
        "band_changed": false
      },
      {
        "input": "heart_rate", "unit": "/min",
        "before": { "obs_id": "Observation/1042", "value": 105, "points": 1 },
        "after": { "obs_id": "Observation/1057", "value": 112, "points": 2 },
        "band_changed": true
      },
      {
        "input": "temperature", "unit": "Cel",
        "before": { "obs_id": "Observation/1042", "value": 37.2, "points": 0 },
        "after": { "obs_id": "Observation/1057", "value": 38.6, "points": 2 },
        "band_changed": true
      }
    ],
    "agent_action": "propose",
    "missing_input": null,
    "complaint": "Short of breath since morning. My mother had chest pain last year.",
    "signs_verdict": "found",
    "signs": [
      {
        "code": "SOB_ACUTE", "gloss": "sudden shortness of breath", "colour": "ORANGE",
        "source": "complaint", "status": "current",
        "quote": "Short of breath", "quote_span": { "start": 0, "end": 15 }, "reason": null
      },
      {
        "code": "CHEST_PAIN", "gloss": "chest pain", "colour": "ORANGE",
        "source": "complaint", "status": "other",
        "quote": "My mother had chest pain", "quote_span": { "start": 31, "end": 55 }, "reason": "not_current"
      }
    ],
    "rationale": "Respiratory rate 22 to 26, heart rate 105 to 112 and temperature 37.2 to 38.6 moved the score from 3 to 6 (YELLOW to ORANGE). Please take a second look.",
    "rationale_source": "model",
    "notices": []
  }
]
```

### POST /proposals/{id}/approve
Request: `colour` is the colour the nurse confirms (normally `proposed_colour`); if it differs, `override_reason` is
required (`422` otherwise). `signs_kept` are the sign codes the nurse keeps ticked. The user is the session user.
`200` returns the command; the Flag and the colour appear when the executor finishes (watch `/proposals/{id}/gates`).
`403` role is not nurse or clinician (a manager). `409` the proposal is no longer pending, or does not exist. Both
refusals are written to `audit_log`.

<!-- example: POST /proposals/{id}/approve request -->
```json
{ "colour": "ORANGE", "signs_kept": ["SOB_ACUTE"], "override_reason": null }
```

<!-- example: POST /proposals/{id}/approve response -->
```json
{
  "proposal_id": "b1f0c3a2-7d4e-4f8a-9c21-5e6a0d3b8f14",
  "command_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "status": "approved"
}
```

<!-- example: error 403 -->
```json
{ "error": { "code": "forbidden", "message": "only a nurse or clinician can approve" } }
```

<!-- example: error 409 -->
```json
{ "error": { "code": "conflict", "message": "proposal is not pending" } }
```

### POST /proposals/{id}/reject
Request `{ "reason": string }` (plain text, required). `200` returns `{ proposal_id, status: "rejected" }`.
`403` and `409` as for approve.

<!-- example: POST /proposals/{id}/reject request -->
```json
{ "reason": "Patient re-measured at the desk, readings were a cuff error." }
```

### POST /proposals/{id}/acknowledge
A superseded proposal that nobody reviewed stays visible as `not_reviewed` until a nurse or clinician acknowledges
it. No body. `200 { "proposal_id": ..., "reviewed": true }`; `409` when it is not superseded or already reviewed.

### POST /notifications/{id}/acknowledge
Dismisses one notice. No body. `200 { "notification_id": ..., "acknowledged": true }`; `404` if unknown.

### Notice codes
Notices appear in `/queue` (per patient, or top level) and in proposals. The UI owns the wording.

| Code | Meaning | Comes from |
|---|---|---|---|
| `remeasure` | an impossible value was refused | notification `remeasure` |
| `no_chart` | no SATS chart for this patient yet | queue (chart selection) |
| `not_reviewed` | superseded proposal nobody reviewed | proposal `status: superseded`, `reviewed: false` |
| `instruction_like_text` | the complaint contained text that looks like an instruction | agent (Q4) |
| `vitals_due` | the site re-check interval has passed | notification `vitals_due` |
| `clinician_reminded` | the clinician on duty was reminded of a pending proposal | notification `clinician_reminder` |
| `model_unavailable` | the language model is down; scoring and proposals continue | notification `model_unavailable` |
| `fhir_unavailable` | the FHIR server could not be reached (Q12); `/queue` then has no patients and this notice at top level | queue (`get_queue_state`) |
| `data_incomplete` | a visit lacks data the queue needs (no patient, unknown colour, no arrival time) | queue (added by M, not in B's first list) |

## 7. Audit, timeline, trace, gates

### GET /audit?visit_id=&run_id=&kind=&limit=
Newest first, `limit` default 100. Rows are the `afya.audit_log` columns. `payload` holds IDs, codes and numbers only.

<!-- example: GET /audit -->
```json
[
  {
    "id": 412, "at": "2026-11-06T08:53:06+00:00", "kind": "command_done", "actor": "nurse-a",
    "auth": "demo_switcher", "visit_id": "v014", "run_id": null,
    "payload": { "command_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "proposal_id": "b1f0c3a2-7d4e-4f8a-9c21-5e6a0d3b8f14", "obs_id": "Observation/1057", "colour": "ORANGE", "attempts": 1 }
  },
  {
    "id": 411, "at": "2026-11-06T08:53:05+00:00", "kind": "proposal_approved", "actor": "nurse-a",
    "auth": "demo_switcher", "visit_id": "v014", "run_id": null,
    "payload": { "proposal_id": "b1f0c3a2-7d4e-4f8a-9c21-5e6a0d3b8f14", "command_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "obs_id": "Observation/1057" }
  },
  {
    "id": 409, "at": "2026-11-06T08:52:30+00:00", "kind": "approve_refused", "actor": "mgr-k",
    "auth": "demo_switcher", "visit_id": null, "run_id": null,
    "payload": { "proposal_id": "b1f0c3a2-7d4e-4f8a-9c21-5e6a0d3b8f14", "reason": "role" }
  }
]
```

### GET /visits/{id}/timeline  (evidence, W2)
Readings oldest first. `values[input].points` is `null` for an input that is shown but not scored (SpO2).
`missing` lists scored inputs the reading did not have (the colour is then a lower bound).

<!-- example: GET /visits/{id}/timeline -->
```json
{
  "visit_id": "v014",
  "chart_id": "sats_adult_2012",
  "readings": [
    {
      "obs_id": "Observation/1042",
      "at": "2026-11-06T08:05:00+00:00",
      "values": {
        "resp_rate": { "value": 22, "unit": "/min", "points": 2 },
        "heart_rate": { "value": 105, "unit": "/min", "points": 1 },
        "systolic_bp": { "value": 120, "unit": "mm[Hg]", "points": 0 },
        "temperature": { "value": 37.2, "unit": "Cel", "points": 0 },
        "spo2": { "value": 97, "unit": "%", "points": null },
        "mobility": { "value": "walking", "unit": null, "points": 0 },
        "consciousness": { "value": "alert", "unit": null, "points": 0 },
        "trauma": { "value": "no", "unit": null, "points": 0 }
      },
      "tews": 3, "colour": "YELLOW", "complete": true, "missing": [], "signs": []
    },
    {
      "obs_id": "Observation/1057",
      "at": "2026-11-06T08:50:00+00:00",
      "values": {
        "resp_rate": { "value": 26, "unit": "/min", "points": 2 },
        "heart_rate": { "value": 112, "unit": "/min", "points": 2 },
        "systolic_bp": { "value": 120, "unit": "mm[Hg]", "points": 0 },
        "temperature": { "value": 38.6, "unit": "Cel", "points": 2 },
        "spo2": { "value": 93, "unit": "%", "points": null },
        "mobility": { "value": "walking", "unit": null, "points": 0 },
        "consciousness": { "value": "alert", "unit": null, "points": 0 },
        "trauma": { "value": "no", "unit": null, "points": 0 }
      },
      "tews": 6, "colour": "ORANGE", "complete": true, "missing": [], "signs": []
    }
  ]
}
```

### GET /runs/{run_id}/trace  (agent trace, W5)
Ordered steps of one agent run. `server` is `ours` (afya-mcp) or `borrowed` (the WSO2 FHIR server) for tool steps and
`null` for model, decision and gate steps. Tool names are the real ones: ours `compute_tews` `check_deterioration`
`get_queue_state`; borrowed `search` `read`. `args_summary` and `result_summary` are short and carry no free text.

<!-- example: GET /runs/{run_id}/trace -->
```json
[
  { "step": 1, "at": "2026-11-06T08:50:02+00:00", "kind": "tool", "server": "ours", "name": "compute_tews",
    "args_summary": "observation_id=Observation/1057", "result_summary": "scored: TEWS 6, ORANGE",
    "latency_ms": 38.2, "tokens_in": null, "tokens_out": null, "cost_usd": null, "cited_ids": ["Observation/1057"] },
  { "step": 2, "at": "2026-11-06T08:50:03+00:00", "kind": "tool", "server": "ours", "name": "check_deterioration",
    "args_summary": "visit_id=v014", "result_summary": "checked: YELLOW to ORANGE, propose",
    "latency_ms": 61.5, "tokens_in": null, "tokens_out": null, "cost_usd": null,
    "cited_ids": ["Observation/1042", "Observation/1057"] },
  { "step": 3, "at": "2026-11-06T08:50:11+00:00", "kind": "model", "server": null, "name": "map_signs",
    "args_summary": "complaint, 66 characters", "result_summary": "1 current sign, 1 other mention",
    "latency_ms": 8200, "tokens_in": 540, "tokens_out": 96, "cost_usd": 0, "cited_ids": [] },
  { "step": 4, "at": "2026-11-06T08:50:30+00:00", "kind": "tool", "server": "borrowed", "name": "search",
    "args_summary": "type=Observation, encounter=Encounter/v014", "result_summary": "2 readings",
    "latency_ms": 120, "tokens_in": null, "tokens_out": null, "cost_usd": null,
    "cited_ids": ["Observation/1042", "Observation/1057"] },
  { "step": 5, "at": "2026-11-06T08:50:41+00:00", "kind": "decision", "server": null, "name": "submit_decision",
    "args_summary": "proposed ORANGE", "result_summary": "proposal created",
    "latency_ms": null, "tokens_in": null, "tokens_out": null, "cost_usd": null,
    "cited_ids": ["Observation/1042", "Observation/1057"] },
  { "step": 6, "at": "2026-11-06T08:50:42+00:00", "kind": "gate", "server": null, "name": "paused_for_nurse",
    "args_summary": "waiting for a nurse or clinician", "result_summary": "no change to the queue",
    "latency_ms": null, "tokens_in": null, "tokens_out": null, "cost_usd": null, "cited_ids": [] }
]
```

Where the steps come from: our tools from the `afya-mcp` audit rows that carry the run's `run_id` (kind = tool name:
`compute_tews`, `check_deterioration`, `get_queue_state`, `record_vitals`, `raise_recheck_flag`, `notify_staff`;
summaries are built by code from the trimmed inputs and outputs). The agent's own steps (model, decision, gate, borrowed
`search`/`read`) must be written by E5 as `audit_log` rows of kind `agent_step` with the same `run_id` and a payload
`{ step_kind: "tool"|"model"|"decision"|"gate", server: "borrowed"|null, name, args_summary, result_summary, latency_ms,
tokens_in, tokens_out, cost_usd, cited_ids }` (IDs, codes and numbers only). An unknown run gives `[]`.

### GET /proposals/{id}/gates  (gate steps, W4)
Always the six gates, in order. `at` is `null` for a gate not reached yet. Refused attempts hang on `confirmed`, with
the role of the person who tried (a manager's refusal is the red ✕ on step 3). `written` is the time the command was
marked done and `audited` the time of its audit row; both are written in one transaction, so they are equal today.

<!-- example: GET /proposals/{id}/gates -->
```json
[
  { "gate": "proposed", "at": "2026-11-06T08:50:41+00:00", "by": "agent", "refused": [] },
  { "gate": "paused", "at": "2026-11-06T08:50:42+00:00", "by": null, "refused": [] },
  { "gate": "confirmed", "at": "2026-11-06T08:53:05+00:00", "by": "nurse-a",
    "refused": [{ "by": "mgr-k", "role": "manager", "at": "2026-11-06T08:52:30+00:00" }] },
  { "gate": "claimed", "at": "2026-11-06T08:53:05+00:00", "by": "nurse-a", "refused": [] },
  { "gate": "written", "at": "2026-11-06T08:53:06+00:00", "by": "nurse-a", "refused": [] },
  { "gate": "audited", "at": "2026-11-06T08:53:06+00:00", "by": "nurse-a", "refused": [] }
]
```

## 8. Demo (DEMO_MODE=1 only, `404` otherwise)

### POST /demo/scenario
Request `{ "name": "p014" }`. Loads the P-014 scenario (first reading YELLOW). Returns the visit.

<!-- example: POST /demo/scenario response -->
```json
{ "visit_id": "v014" }
```

### POST /demo/scenario/next
No body. Adds the scenario's next reading (for P-014 the one that raises the score to ORANGE).

<!-- example: POST /demo/scenario/next response -->
```json
{ "obs_id": "Observation/1057" }
```

## 9. Open questions for M

Each has B's proposal. **Mahdi accepted all of Q1 to Q13** (Q6 with the any-level override above); the answers are in the last column and in the backlog (E0-5 Notes).

| # | Question | B's proposal | Answer (M) |
|---|---|---|---|
| Q1 | The backend has no place for the **complaint**: `record_vitals` takes no complaint and nothing stores it. The architecture fixes the limit (500 characters, NFKC-normalised, only `map_signs` sees it) but not where it is stored. | Store it with the reading in Postgres (not in FHIR, so it never reaches the model as FHIR text). | **Answer: accepted (stored in Postgres next to the reading, table `afya.readings`, never in FHIR).** |
| Q2 | `patient_label` | B puts it on the Patient as identifier system `urn:afya:label` in the seed (E5-1, E2-6); the API reads it. No names anywhere. | **Answer: accepted (`patient_label` read from Patient.identifier `urn:afya:label`).** |
| Q3 | `get_queue_state` has no `patient_label`, no `last_reading.tews`/`colour`, no `flags`, and notices are free-text strings. | Add them in the API or the tool; `notices` become codes from section 6. | **Answer: accepted (`get_queue_state` returns `patient_label`, `last_reading.tews`/`colour`, `flags`, notices as codes).** |
| Q4 | `insert_proposal` validates only `to_colour` and `cited_obs_ids`. The card also needs `current_colour`, `tews_before/after`, `reasons`, `evidence`, `complaint`, `signs`, `rationale`, `notices` (incl. `instruction_like_text`). | Put them in `payload` with exactly the names above and validate them in `_check_payload`. | **Answer: accepted (field names as listed, validated in `workflow._check_payload`).** |
| Q5 | `compute_tews` returns points and record ids but **not the raw values** (`check_deterioration.changes` neither). | The timeline and `evidence` read values from the FHIR Observation (`observation_values`). | **Answer: accepted (values read from the FHIR Observation, E6-5).** |
| Q6 | Architecture section 7: "the nurse can untick a sign or override the colour with a reason", but `approve_proposal(conn, proposal_id, user_id)` has no colour, `signs_kept` or reason, and there is no `reject_proposal`. May the override be lower than proposed? | Add `colour`, `signs_kept`, `override_reason` (audited); add `reject_proposal` with the same role check. | **Answer: accepted, with one decision: the nurse or clinician may override the colour to ANY level, including lower than proposed, with a mandatory reason; the agent itself still never proposes a downgrade.** |
| Q7 | Notice names: the backlog says `clinician_reminded`, the database says `clinician_reminder`. | The API translates to `clinician_reminded`. | **Answer: accepted (API translates `clinician_reminder` to `clinician_reminded`).** |
| Q8 | `run_id` / thread id is `visit:obs_id`; the observation id contains a slash if given as a reference. | Use `v014:1057` (bare id), URL-safe. | **Answer: accepted (`run_id` = `<visit_id>:<bare observation id>`).** |
| Q9 | `proposals.obs_id` is stored as given (bare or `Observation/…`). | The API always returns `Observation/<id>`; `ref_id` already accepts both. | **Answer: accepted (API always returns `Observation/<id>`).** |
| Q10 | Error body shape. | As in section 1. | **Answer: accepted.** |
| Q11 | Architecture Appendix B names the model-facing WSO2 tools `fhir_search` and `fhir_read`; the live WSO2 server calls them `search` and `read`. Which name does the trace show? | The real server's name (`search`, `read`) with `server: "borrowed"`; the wrapper name only in the model prompt. | **Answer: accepted (real names `search` and `read`, `server: "borrowed"`).** |
| Q12 | Architecture section 10: "FHIR down: retry 3 times, then warn the nurse". The backlog's 7 notice codes have none for it. | Add `fhir_unavailable` to the notice list (the UI shows it like `model_unavailable`), or reuse a top-level notice. | **Answer: accepted (`fhir_unavailable` added to the notice codes).** |
| Q13 | `agent_action`, `missing_input`, `signs_verdict`, `rationale_source` come from `submit_decision` and `map_signs` (Appendix B) and must be kept in the proposal payload (with Q4). | As in the `/proposals` example. | **Answer: accepted (kept in the proposal payload with Q4).** |
