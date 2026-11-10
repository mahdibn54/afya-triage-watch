# Architecture

Afya Triage Watch flags a waiting patient for a second look and cites the readings; a nurse or clinician confirms every
change. Research prototype on synthetic data. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · design PDF:
[`docs/architecture-v4.1.pdf`](docs/architecture-v4.1.pdf) · results: [`EVALS.md`](EVALS.md).

```
 nurse UI (Next.js, 127.0.0.1:3000) ──► api (FastAPI + LangGraph agent) ──► open-weights model (gpt-oss-120b)
                                          │            │
                       afya-mcp (built) ◄─┘            └─► WSO2 FHIR MCP (borrowed) ─► GET-only gateway ─► HAPI FHIR
          /read (model) · /act (executor only) · /ui        read-only search/read of the patient record
                 │                                  │
           Postgres: proposals, commands,     HAPI FHIR: Patient, Encounter (colour), Observation (reading), Flag
           checkpoints, append-only audit
```

## The agent loop

One LangGraph run per saved reading (`api/afya_api/agent.py`):

`validate` → `record` → `score` → `deteriorate` → `map_signs` (model) → `trigger` → `investigate` (model) → `proposal` →
`paused` (waits for a person) → `executor` (only after approval).

- **Fixed code decides.** The SATS early warning score, the colour and the trigger come from `mcp/afya_mcp/rules.py`
  and the chart in `rules/`. The model never computes them, can add urgency but never remove it, and a colour rise
  always becomes a proposal.
- **The model does two things:** it maps the free-text complaint (English, French, Swahili, code-switched) to SATS
  warning signs, and it investigates by choosing up to 4 read-only tool calls (earlier readings, band changes, wait time)
  before it submits a decision.
- **Its words are checked.** A model rationale is shown only if every number and record id is real, it names the
  proposed colour and the driving sign, and it states no other colour change. Otherwise code writes the sentence.
- **Recovery.** A timeout, invalid output, provider limit or circuit-breaker trip ends as `model_unavailable`: the run
  continues on the fixed rules and the card says "no model". A failed write is retried idempotently, then abandoned
  with a notice; nothing half-written reaches the record.

## MCP: one built, one borrowed

| Server | Tools | Why |
|---|---|---|
| **afya-mcp** (ours) | read: `compute_tews`, `check_deterioration`, `get_queue_state` · act: `record_vitals`, `raise_recheck_flag`, `notify_staff`, `seed_demo_visit` · ui: screen data | Scoring, queue state and every write need our rules and our audit. Act tools are never offered to the model. Each mount is an OAuth 2.1 protected resource with its own scope. |
| **WSO2 FHIR MCP** (borrowed, Apache-2.0) | `search`, `read` | Generic FHIR reads are not worth rebuilding; a GET-only gateway in front of HAPI makes it read-only. |

## Human gate and audit

1. The agent writes a proposal; nothing in FHIR changes, and the run pauses (LangGraph `interrupt`).
2. A nurse or clinician approves or rejects it; the decision records their name and role. Managers can only read.
3. On approval, a single-use command is committed, and the executor writes a FHIR Flag and the new colour.

Every tool call and agent step writes an audit row (inputs, output, latency, user, run id) **before** its result is used.
If the row cannot be written, the call fails and the run stops. The app's database role can only insert into and read
the audit log, never change or delete it. The complaint text itself is never logged.

## Model, data and cost

- **Open weights only.** `gpt-oss-120b` (Apache-2.0) by default, via `MODEL_PROVIDER`: Groq, Ollama Cloud, OpenRouter
  (Qwen3) or a local Ollama.
- **Data stays in-country.** Hosted providers are called only while `DATA_CLASSIFICATION=synthetic`, enforced in code.
  A real deployment runs the same open weights on a server in the country (the local `ollama` option). Patient names
  and free text from FHIR are never sent to the model.
- **Cost per run.** About 2,000–3,000 tokens (2 to 4 model turns). That is $0 on Groq's free plan or a local model.
  Tokens, seconds and billed cost are logged per call.
- **Networks.** Only the nurse UI is published, on localhost. The borrowed server cannot reach afya-mcp or the
  authorization server.
