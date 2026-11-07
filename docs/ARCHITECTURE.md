# Architecture on one page

Decision support for trained triage staff: the agent flags a patient for a second look and cites the readings; a nurse or
clinician confirms every change. Research prototype on synthetic data. Full design: `docs/architecture-v4.1.pdf`.

## Agent shape

A LangGraph run starts for every saved reading (`api/afya_api/agent.py`). Fixed code does everything that matters:

`validate` → `record` → `score` (SATS points, colour) → `deteriorate` (compare with the confirmed colour) → `map_signs`
(model: warning signs from the complaint) → `trigger` (fixed rules) → `investigate` (model, at most 4 read-only tool
calls, then `submit_decision`) → `proposal` → `paused` (LangGraph `interrupt`) → `executor` (only after approval).

- **What the model investigates (E12-5).** The investigate prompt hands the model the code-decided trigger, the current
  reading's id, score, colour and missing inputs, the previous reading's record id and the validated sign codes, not
  the earlier values or the per-input changes. When the case needs them the model fetches them itself: the borrowed
  WSO2 `search`/`read` for the readings' values and times (oldest first, the current one marked), afya-mcp
  `check_deterioration` for which inputs moved band and `get_queue_state` for the wait and the re-check. The prompt says
  when each tool is worth a call (a colour rise: values and band changes; a sign-only trigger with no earlier reading:
  none). One fixed reminder if the model answers in text instead of a tool call; at most 4 reads and 5 turns.
- Scores, colours and triggers come from `mcp/afya_mcp/rules.py` and the chart in `rules/`; the model never computes them.
- The model can add urgency, never remove it; a colour rise always becomes a proposal. Tools take record IDs, not numbers.
- Model text is shown only if every number, record id and word passes `decision.rationale_text` (and no value, score or
  record id is written later-to-earlier); otherwise the code builds the sentence. Any model failure means the `model_unavailable` notice and the run goes on with the rules.
- **Model provider.** Always an open-weights model; `MODEL_PROVIDER` picks where it runs: `ollama_cloud` (code default,
  `gpt-oss:120b`), `groq` (GroqCloud free plan, `openai/gpt-oss-120b`, the provider of the recorded live run and the
  Groq eval runs), `openrouter` (Qwen3-30B-A3B-Instruct-2507 pinned to one provider, no fallback) or a local `ollama`.
  A hosted model is called only while `DATA_CLASSIFICATION=synthetic` (guard in code, checked twice); anything else
  refuses it. Tokens, seconds and the billed cost (0 on Groq's free plan and a local model) are logged per call in the
  trace. Provider limits (429, daily limits) mean "model unavailable" and the rules-only proposal. Free text from FHIR
  never reaches the model.
- A watch loop (`watch.py`) reminds staff of overdue re-checks and unanswered proposals.

## MCP servers: built and borrowed

| Server | Why |
|---|---|
| **afya-mcp (built)**: `/read/mcp` for the model, `/ui` for the api, `/act/mcp` for the executor only | Scoring, queue state and every write need our rules and our audit. Write tools are never offered to the model. Every mount is an OAuth 2.1 protected resource (see "Service authorization"); only `/healthz` and the protected-resource metadata are open. |
| **WSO2 FHIR MCP (borrowed, Apache-2.0)** | Generic FHIR `search`/`read`. Not worth rebuilding; made safe by a GET-only nginx gateway in front of HAPI. |

## Networks and data layer

Only the UI is published (`127.0.0.1:3000`). Internal networks: `app` (Postgres, afya-mcp, api), `mcp` (api to afya-mcp),
`auth` (api, afya-mcp and the authorization server), `borrowed` (api and WSO2 only: WSO2 runs without authorization and
cannot reach afya-mcp or the authorization server), `fhir_ro` (WSO2 and the gateway), `fhir_rw` (afya-mcp, gateway, HAPI),
`web` (UI and api).

## Service authorization (MCP OAuth 2.1, E13-3)

afya-mcp follows the MCP authorization profile of protocol 2026-07-28. Its callers are services (the api and the host-side
eval harness), never a browser, so they use the OAuth 2.1 **client-credentials** grant with a pre-registered confidential
client (`afya-api`). Authorization code with PKCE is for a user's browser or app acting through MCP; there is none here.
The nurse signs in to the api, not to MCP, and her approval stays a separate application gate (role check, single-use
command) in front of every write: an access token never replaces it.

| Piece | Choice |
|---|---|
| Authorization server | Authelia 4.39.28 (Apache-2.0), pinned by digest, service `auth` on the internal `auth` network, HTTPS with a local CA (`auth/init.sh`), about 60 MB RAM. RFC 8414 metadata, RFC 8707 resource indicators, RFC 9068 JWT access tokens, 5-minute lifetime. Nobody signs in to it. |
| Resources and scopes | One protected resource per mount: `http://afya-mcp:9000/read/mcp` (`afya:read`), `/act/mcp` (`afya:act`), `/ui/mcp` (`afya:ui`). RFC 9728 metadata at `/.well-known/oauth-protected-resource/<mount>/mcp`. |
| Resource server | `mcp/afya_mcp/auth.py`: the SDK's bearer middleware and metadata routes with a JWKS verifier (signature, exact issuer, audience = the mount, expiry, `typ` at+jwt, asymmetric algorithms only). 401 `invalid_token` or 403 `insufficient_scope`, with `resource_metadata` and `scope`. Every request needs a token, `server/discover` included. |
| Client | `api/afya_api/mcp_client.py`: the SDK's `ClientCredentialsOAuthProvider` per mount, asking for that mount's resource and scope only, credentials sent only to the configured issuer. The model-facing read path therefore only ever holds an `afya:read` token for `/read/mcp`; `afya:act` tokens exist only on the fixed-code `/act` path (executor after approval, saving vitals, notices). |
| Never | a token in a URL or a log; any afya credential sent to WSO2; a client secret in afya-mcp. |

Known limit: afya-mcp itself stays plain HTTP on the internal `mcp` network (no published port), while OAuth 2.1 asks for
TLS wherever bearer tokens travel; tokens are short-lived and bound to one mount. TLS on afya-mcp is the next step.

Protocol conformance (E13-4): the official MCP conformance tool (pinned alpha, requirement set 2026-07-28) was run against all three mounts and the api's client; results, the triage of every failure and the expected-failures list are in [docs/conformance/final-2026-07-28.md](conformance/final-2026-07-28.md). It is not AAIF certification and not a clinical validation.

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

The audit trail fails closed (E12-6). Our tools (`read`, `ui`, `act`) return a result only after its audit row (inputs,
output, latency, timestamp) is written; act tools also write an intent row first and do nothing without it. The one
exception is `queue_state`, the boards' polling. Each agent step is an `agent_step` row; if one cannot be written after
three attempts the run stops (no proposal, no code-built fallback from an unlogged step) and the nurses get the
`agent_failed` notice. A borrowed WSO2 read stores the exact projected result the model received (ids, codes, values,
units, times; capped, plus a hash of the full result and of the raw payload, never free text). The complaint text is
never logged (its length only).
