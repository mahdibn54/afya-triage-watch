# Agent and MCP competition audit

Audited source revision: `28215e1`. Scope: technical implementation and evidence against the
[official healthcare brief](https://agentic-africa-challenge.lovable.app/tracks/healthcare).
No clinical code, fixture labels or model configuration changed. No live model calls were made.
This report is evidence, not a second backlog. Dates and personal eligibility are outside its scope.

## E8-2 repair follow-up

The two harness regressions below have been repaired. Compose now passes the required server token to `group-a`,
Group A CI generates a fresh token, and the nurse audit INSERT explicitly sets `auth=demo_switcher`. The test also
verifies that auth remains unchanged after refused mutations. No clinical code, permissions or constraints changed.

Fresh disposable project `afya-e8-2-fix`, local marker `73ee041+e82-fix`: the checked-in harness passed **25/25**
real-stack cases without additional token/command overrides, **3/3** inside-WSO2 isolation cases, and **2/2**
desktop/mobile approval workflows, with no retries or skipped tests. Eight viewport screenshots were inspected;
harness lint passed. JUnit and screenshots are under ignored `.playwright-mcp/group-a/`. CI token generation was
updated; these local results do not claim the remote CI run has passed. Original failure counts below are retained
as historical audit evidence and are superseded for the harness by this follow-up.

## AAIF alignment and MCP protocol-version follow-up

### Assigned implementation follow-up: Mahdi

Dheker explicitly assigned the following work to **Mahdi (M)**. All four items are planned, not implemented or
verified complete. The source of truth for ownership, dependencies and status is **E13-1 through E13-4** in the
[existing project backlog](Afya_Tasks_BMAD.md). This instruction authorizes the scope addition; it does not claim
that the competition mandates the newest protocol or that AAIF has certified the application.

| Backlog story | Assigned work | Plain-English purpose |
|---|---|---|
| E13-1 | Upgrade the MCP client/server integration to the current protocol | Update how services communicate, using a compatible SDK and preserving the borrowed WSO2 connection. Recheck the published current revision when implementation begins. |
| E13-2 | Implement current MCP server discovery | Let clients ask who the server is, which protocol versions it supports and which capabilities it offers. `tools/list` remains the tool catalogue; discovery does not grant access to patient data. |
| E13-3 | Implement standardized MCP authorization | Replace reliance on the shared service secret with the selected standard OAuth 2.1 flow, discovery metadata, scoped tokens and server-side validation. Choose the appropriate user/service identity arrangement; tool access must never bypass nurse confirmation. |
| E13-4 | Run official MCP conformance testing | Use the MCP project's test framework to check protocol messages and behavior against explicit revisions. Record actual pass/fail reports, tool version, tested revision and code commit. This complements application/security/browser tests and is not clinical validation or automatic AAIF certification. |

Conformance testing sends protocol requests to servers, or tests clients against controlled servers, then examines
responses for specification compliance. It covers areas such as discovery/version handling, tool schemas/calls,
transport/errors and applicable authorization behavior. Establish the existing-protocol baseline before migration
where feasible, then test the selected current revision after migration. Do not treat skipped or baselined failing
checks as proof of passing conformance. Source: [official MCP conformance framework](https://github.com/modelcontextprotocol/conformance/blob/main/README.md).

Migration and authorization are separate changes. Our current API explicitly calls `initialize`; the newer
protocol uses per-request metadata and mandatory server discovery. SDK, client adapter, server configuration,
dependency constraints and tests need review. LangGraph checkpoints and fixed clinical rules remain separate
from protocol sessions. Standard authorization adds permission discovery, an identity service and expiring,
appropriately scoped tokens; clinician approval of a consequential action remains a separate application gate.
Sources: [protocol changes](https://modelcontextprotocol.io/specification/2026-07-28/changelog),
[discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover),
[authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).

Checked against source revision `b7aa6d7` and the official sources below. AAIF hosts open protocols and projects;
its project portfolio is not evidence that an application must use every hosted project. The challenge explicitly
allows LangGraph. No separate AAIF entrant rulebook or requirement to use Goose/A2A was found in the inspected
AAIF/competition pages. Organizer material describes AAIF involvement; this review does not establish funding terms.
Sources: [AAIF about](https://aaif.io/about), [AAIF projects](https://aaif.io/projects),
[healthcare build requirements](https://agentic-africa-challenge.lovable.app/tracks/healthcare).

There is a concrete distinction between using real MCP and claiming full conformance to the current specification:

| Check | Observed result |
|---|---|
| Installed official Python SDK | `mcp` 1.30.0; `LATEST_PROTOCOL_VERSION` is `2025-11-25`. The project allows `mcp>=1.9,<2`; a range is not a pin to this installed version. |
| Older-protocol interoperability | In-process ASGI check: `initialize` negotiates `2025-11-25`, `tools/list` returns the three expected read tools, HTTP 200. Earlier real-container checks also demonstrated working own/borrowed calls. |
| Invalid Origin | In-process request with valid bearer token, permitted Host and invalid Origin returns HTTP 403. This checks the Origin boundary separately from the Host check. |
| Current protocol | The official versioning page identifies `2026-07-28` as current. Its discovery specification requires `server/discover`. Our request with that protocol header returns HTTP 400, explicitly listing supported versions through `2025-11-25`. The discovery method on the supported transport version produces JSON-RPC error `-32602`, not a discovery result. |
| Authorization interoperability | The code uses a shared static service bearer token. It does not provide standard OAuth authorization-server/protected-resource discovery, user-delegated scopes or that OAuth flow. The MCP authorization feature is optional; this custom private-service policy must not be represented as implementation of MCP's OAuth authorization profile. |
| Official conformance suite | Not run. Application/security tests and targeted ASGI probes are not proof that every normative protocol requirement passes. Neither AAIF certification nor full current-version conformance has been established. |

Protocol sources: [current version and negotiation](https://modelcontextprotocol.io/specification/versioning),
[current discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover),
[legacy transport security](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization),
[official conformance tooling](https://github.com/modelcontextprotocol/conformance/blob/main/README.md).
Code: [server.py](../mcp/afya_mcp/server.py), [mcp_client.py](../api/afya_api/mcp_client.py),
[MCP package requirements](../mcp/pyproject.toml).

Conclusion: the implemented agent/MCP architecture fits the published competition stack and AAIF's open ecosystem.
It is a functioning older-protocol MCP implementation, not verified full current-specification conformance.
The inspected competition brief does not mandate the newest protocol revision or AAIF certification, so this gap
alone does not establish competition ineligibility. Dheker subsequently authorized the four Mahdi-owned E13 stories
above; no runtime code was changed by this documentation update.

**Conclusion: most core mechanisms are implemented, but complete technical compliance is not yet established.**
The outstanding issues are current model-on execution evidence and audit completeness under logging failure.
The harness regressions found in the original audit are resolved as documented above.
See the separate licensing and submission notes below.

## Implementation mapping

| Requirement | Verdict | Source and observed behavior |
|---|---|---|
| Own MCP: three distinct tools and meaningful action | Implemented | Live `tools/list`: `/read/mcp` exposes `compute_tews`, `check_deterioration`, `get_queue_state`; `/act/mcp` exposes `record_vitals`, `raise_recheck_flag`, `notify_staff`, `seed_demo_visit`. Scoring performs work in fixed code; approved execution creates a FHIR Flag and sets Encounter priority. [server.py](../mcp/afya_mcp/server.py), [services.py](../mcp/afya_mcp/services.py). |
| Borrowed MCP with a reason for reuse | Implemented | The running pinned WSO2 server exposes seven tools, including `search` and `read`. Our model wrappers use those reads for visit-scoped Observations. [investigate.py](../api/afya_api/investigate.py), line 136; reuse rationale in [ARCHITECTURE.md](ARCHITECTURE.md). WSO2 also advertises writes, but the GET-only gateway blocks them; server advertisement is not permission to write. |
| Open-source orchestration and autonomous tool use/recovery | Implemented; real-model demonstration incomplete | LangGraph graph plus bounded model/ToolNode investigation subgraph. The model can choose own or borrowed reads, inspect results and submit a decision. Four-read/five-turn budget, citation checks, checkpoint resume and rules-only fallback exist. [agent.py](../api/afya_api/agent.py), line 184; [investigate.py](../api/afya_api/investigate.py), line 271. A scripted model selecting a forged write was refused in the real-service suite. Historical model limitations are below. |
| Open-weights task and protected data boundary | Historical evidence; current-default proof missing | Tracked local Qwen trials produce sourced proposals. Compose currently defaults to Ollama Cloud `gpt-oss:120b`, without a recorded complete run on this revision. Remote backends refuse non-synthetic classification; local Ollama remains supported. [model.py](../api/afya_api/model.py), lines 223, 358, 496; [Compose](../docker-compose.yml); [EVALS.md](../EVALS.md). Environment classification is a guard, not verification of a patient's provenance or deployment geography. |
| Consequential changes require named human confirmation | Implemented in this prototype | LangGraph interrupts; approval derives the actor from the signed session, checks nurse/clinician role, stores a command and decision atomically, then resumes a fixed executor. Expired, stale, reused and competing commands are checked. Managers cannot approve. [routes_proposals.py](../api/afya_api/routes_proposals.py), [workflow.py](../mcp/afya_mcp/workflow.py), line 360; [agent.py](../api/afya_api/agent.py), line 318. Names are synthetic demo identities, not verified professional identities or production staff authentication. |
| Logged actions, inputs, outputs and timestamps | Partial under failure | Own tools normally write capped input/output audit payloads; writes have an intent or transactional completion record. Borrowed-tool trace rows contain summaries and cited IDs, not exact full returned results. Agent trace writes retry twice, then increment `trace_gaps` and continue. Own read-tool audit failure also permits the read to complete. Thus an unconditional claim that every call is durably logged is stronger than the code. [audit.py](../mcp/afya_mcp/audit.py), [steps.py](../api/afya_api/steps.py), line 38; [investigate.py](../api/afya_api/investigate.py), lines 146-185. |
| Deterioration Watch, established scale, sourced decisions, no diagnosis/prescribing | Implemented, with documented model limitations | SATS chart and fixed-code scorer; recheck changes and `reported_worsening` can propose a second look. Evidence cites stored readings; complaint signs require allow-listed codes and matching quotes. Model text passes a fact/word check or is replaced with a code sentence. Neither watch reminders nor proposals change confirmed priority. [rules.py](../mcp/afya_mcp/rules.py), [signs.py](../api/afya_api/signs.py), [decision.py](../api/afya_api/decision.py), [watch.py](../api/afya_api/watch.py). These are tested boundaries, not clinical validation. |

## Fresh runtime verification

All services ran in disposable project `afya-e8-2-audit`, with fresh synthetic-only databases.
Real Postgres, HAPI, nginx, WSO2, afya-mcp, API and production Next.js were used. Model behavior was disabled
or scripted at the model boundary; none of these results proves live model performance.

| Check | Result and limit |
|---|---|
| Production image build | Passed, including Next.js production build and TypeScript. |
| API suite, real isolated `afya_test`, fake FHIR/scripted model | 200 passed, no skips. Initial host-only run was 102 passed/98 skipped before the test database was supplied. |
| MCP suite, real isolated `afya_test`, fake FHIR | 272 passed, no skips. Includes live-protocol TestClient tool schemas, bearer/Host checks, scoring and DB workflow. |
| Real Group A suite, repository configuration unchanged | **20 failed, 5 passed.** The `group-a` container omits `AFYA_MCP_TOKEN` although the server requires it; calls fail 401. |
| Real Group A suite, temporary token supplied to test process | **24 passed, 1 failed.** Remaining test inserts an audit row without the now-required `auth` column. No source patch was applied. |
| Independent audit permission probe with current schema | INSERT with `auth='service'` succeeded as `afya_app`; UPDATE, DELETE and TRUNCATE each raised `InsufficientPrivilege`; inserted row remained. |
| Inside actual WSO2 container | 3 passed: gateway works, HAPI DNS unavailable, direct HAPI IP connection refused. |
| Browser workflow | Mobile passed; desktop first attempt failed with ECONNRESET fetching proposals. No container restart/OOM was observed. One desktop retry passed (44 s). Both successful runs assert pre-approval YELLOW, manager 403/read-only UI, six nurse-confirmation gates, post-approval ORANGE/Flag, keyboard focus, no document overflow and no browser exceptions. |

The 24 passing real-stack cases cover fixed-code controls, impossible values saving nothing, unconfirmed first visit,
child/no-chart behavior, model-outage proposal fallback, deduplication, forged model write refusal, actual WSO2
write refusal, gateway bypasses, role checks, concurrent approval, stale/expired commands, superseded visibility,
FHIR failure/recovery and retry after a lost successful Flag response. See [coverage matrix](../evals/stack/README.md).

Artifacts under ignored `.playwright-mcp/group-a/`: `competition-unmodified.xml`, `competition-auth-corrected.xml`,
`competition-api.xml`, `competition-mcp.xml`, `competition-isolation.xml`, and browser screenshots/traces.
Tests used code marker `28215e1`; only this report and backlog notes were uncommitted during the audit.
Desktop retry evidence is separately preserved under `.playwright-mcp/competition-browser-retry/`.
Eight successful-run viewport screenshots were visually inspected. The mobile demo drawer/sticky header can
obscure portions of the board or gate list in these captures; passing document-overflow checks does not establish
that every panel element fits at once. These existing UI limitations are separate from the tested approval boundary.

### Harness defects found at the audited revision (now repaired)

1. [evals/stack/compose.yml](../evals/stack/compose.yml) must pass the configured `AFYA_MCP_TOKEN` to `group-a`.
   Supplying a valid token at runtime changes the suite from 20 failures to one. The production API already receives it.
2. [test_gates_live.py](../evals/stack/test_gates_live.py), line 97, must include the correct `auth` in its test INSERT.
   This is an outdated fixture against the current NOT NULL schema, not evidence that audit mutation is allowed.

Both belong to existing B-owned E8-2/E0-6 verification work. Do not call the checked-in real-stack/CI suite green
until it runs unchanged and passes. This audit records the defects without changing agent code or weakening assertions.

## What the real-model logs prove

All four active JSONL files are tracked. The evidence review parsed them and recalculated outcomes with
`evals.metrics.outcome_correct`, without model calls or relabeling.

| Logged condition | Cases / trials | Trial outcomes matching labels | Decision/completion evidence |
|---|---|---|---|
| Qwen3 8B, revision `06a944d` | 18 / 90 | 80 / 90 | 45 valid model `submit_decision`, 45 paused proposals, 45 no-proposal endings. |
| Qwen3 4B instruct, revision `06a944d` | 18 / 90 | 75 / 90 | All 40 proposals use the code fallback because the model returns no valid final decision. |
| Rules-only original fixtures, revision `b175411` | 18 / 18 | 14 / 18 | No model run. |
| Rules-only synthetic set, revision `b175411` | 20 / 20 | 17 / 20 | No model run; includes two intended input refusals. |

The [8B log](../evals/runs/20261106T143727Z_m_fixtures_B_qwen3_8b.jsonl), line 1, records `m01-p014`,
run `2756:2758`, citing observations `2757` and `2758`, with model-sourced rationale and pause before writes.
The harness intentionally does not approve proposals, so this is not evidence of a model-on
nurse-confirmation-to-FHIR completion.

The 8B model selected `submit_decision` directly: its scoring/deterioration calls were graph-driven and it selected
no borrowed reads. The [4B log](../evals/runs/20261106T143727Z_m_fixtures_B_qwen3_4b-instruct.jsonl)
contains 40 borrowed searches and additional own-server reads, but no valid final model decision on those proposals.
No inspected historical trial demonstrates both model-selected borrowed tools and successful final model decision.
That is an agentic-depth evidence gap, not proof that the tool loop is unimplemented, nor a requirement that every
routine task must make an unnecessary borrowed call.

EVALS discloses an unresolved chest-pain failure, builder-authored labels, repeated-run statistics, and the revision
difference. It meets the minimum documented task count, but no held-out model run or current-default run is evidenced.
The synthetic set's 14 held-out cases have rules-only outcomes. Preserve these distinctions in any demonstration.

## Separate documentation and submission gaps

- Code carries MIT, but [LICENSE](../LICENSE) excludes required `rules/charts/`, and the [chart notice](../rules/charts/NOTICE.md)
  restricts that data pending permission. This audit does not establish that the whole runnable package meets the
  competition's OSI licensing condition. The notice says permission was requested; E0-3 says sending was deferred.
  Resolve the factual discrepancy and rights/organizer position; this is not a legal determination about scoring facts.
- [ARCHITECTURE.md](ARCHITECTURE.md) contains built/borrowed rationale and approval/write order, but still names
  OpenRouter as default. [EVALS.md](../EVALS.md) also contains stale default-provider references. Compose now uses
  Ollama Cloud. Historical results should keep their actual model/provider names.
- README provides Compose startup after environment setup. This audit starts real services successfully, but does
  not complete E2-7's independent clean-machine verification or establish anonymous public repository access.
- No public demo-video URL or separate submission description was found; E10-4/E10-3 remain open. No named
  nurse interview/field-note evidence was found; E9 remains open. These are submission/workflow-fit gaps rather
  than missing MCP tools. See the [existing backlog](Afya_Tasks_BMAD.md).

## Next work, within the existing backlog

1. E8-2 harness regressions: repaired and verified without overrides; follow the pushed CI run separately under E0-6.
2. E5-11/E8-3/E8-6: record one current open-weights run, with actual model-selected tool use where useful,
   a valid decision, cited proposal, named human approval, all gates and durable tool trace. Record actual latency,
   tokens, provider and cost; keep a failure/recovery visible. Then complete the declared held-out evaluation.
3. E4-8/E12 audit work: resolve the best-effort trace/read logging policy before claiming every call has a durable
   input/output record, including borrowed reads. Preserve clinical gating and avoid logging sensitive free text.
4. E10-2/E10-1/E0-3: reconcile provider documentation and chart permission/licensing evidence. Finish remaining
   submission artifacts separately; no extra product features are needed for this audit.
