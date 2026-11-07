# Architecture on one page

Decision support for trained triage staff: the agent flags a patient for a second look and cites the readings; a nurse or
clinician confirms every change. Research prototype on synthetic data. Full design: `docs/architecture-v4.1.pdf`.

## Agent shape

A LangGraph run starts for every saved reading (`api/afya_api/agent.py`). Fixed code does everything that matters:

`validate` → `record` → `score` (SATS points, colour) → `deteriorate` (compare with the confirmed colour) → `map_signs`
(model: warning signs from the complaint) → `trigger` (fixed rules) → `investigate` (model, at most 4 read-only tool
calls, then `submit_decision`) → `proposal` → `paused` (LangGraph `interrupt`) → `executor` (only after approval).

- Scores, colours and triggers come from `mcp/afya_mcp/rules.py` and the chart in `rules/`; the model never computes them.
- The model can add urgency, never remove it; a colour rise always becomes a proposal. Tools take record IDs, not numbers.
- Model text is shown only if every number, record id and word passes `decision.rationale_text`; otherwise the code builds
  the sentence. Any model failure means the `model_unavailable` notice and the run goes on with the rules.
- **Model provider.** Default OpenRouter, open-weights Qwen3-30B-A3B-Instruct-2507 pinned to one provider with no fallback;
  optional local Ollama. The hosted model is called only while `DATA_CLASSIFICATION=synthetic` (guard in code, checked
  twice); anything else refuses it. Billed cost per call is logged in the trace. Free text from FHIR never reaches the model.
- A watch loop (`watch.py`) reminds staff of overdue re-checks and unanswered proposals.

## MCP servers: built and borrowed

| Server | Why |
|---|---|
| **afya-mcp (built)**: `/read/mcp` for the model, `/ui` for the api, `/act/mcp` for the executor only | Scoring, queue state and every write need our rules and our audit. Write tools are never offered to the model. Every mount needs a bearer token (`AFYA_MCP_TOKEN`), only `/healthz` is open. |
| **WSO2 FHIR MCP (borrowed, Apache-2.0)** | Generic FHIR `search`/`read`. Not worth rebuilding; made safe by a GET-only nginx gateway in front of HAPI. |

## Networks and data layer

Only the UI is published (`127.0.0.1:3000`). Internal networks: `app` (Postgres, afya-mcp, api), `mcp` (api to afya-mcp),
`borrowed` (api and WSO2 only: WSO2 runs without authorization and cannot reach afya-mcp), `fhir_ro` (WSO2 and the gateway),
`fhir_rw` (afya-mcp, gateway, HAPI), `web` (UI and api).

Postgres holds proposals, single-use commands, readings with the complaint, agent checkpoints and the audit log. FHIR (HAPI)
holds the clinical record: one reading is one Observation; the confirmed colour is `Encounter.priority`.

## Write order: Postgres, then FHIR

1. The agent writes a proposal row (nothing in FHIR changes). The run pauses.
2. A nurse or clinician approves: in one transaction the proposal is decided and a command row is committed (the intent).
3. The executor claims the command (advisory lock), then writes to FHIR with a conditional create keyed on the command id
   (a retry converges to the same Flag; the colour is an absolute set).
4. Mark the command done and write its audit row in one transaction. A crash between 3 and 4 is repaired by resuming the
   claimed command; a command that keeps failing is abandoned with a `command_abandoned` notice and nothing reaches the record.

## Gates and append-only audit

Six gates, shown in the UI: proposed, paused, confirmed (role check; managers read only), claimed, written, audited.
The app database role cannot UPDATE or DELETE `audit_log` (column-level INSERT and SELECT only), and has UPDATE only on
named status columns of proposals and commands. A database administrator can still rewrite the log (no hash chain: parking lot).
Every action carries the user, role and run id.
