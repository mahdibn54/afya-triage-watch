# Group A: real-stack fixed-code and security checks (E8-2)

These tests use real Postgres, HAPI, nginx, WSO2, afya-mcp, API and LangGraph checkpoints. They are separate from
the earlier in-memory FHIR tests. No model service/key/GPU is needed: the application model is disabled, and
model-dependent refusal/outage cases use the existing deterministic `ScriptedBackend` at that boundary only.
All patients are invented `GA-*` visits; the E5-1 tuning/held-out dataset is untouched.

Set `AFYA_MCP_TOKEN` in the selected environment file along with the database passwords and session secret.
The overlay passes that same token to the test client and the server; no extra `docker compose run -e` override
is needed. CI generates a fresh token for each run. The audit-permission fixture supplies `auth=demo_switcher`
for its synthetic nurse, matching the current schema, and still requires UPDATE/DELETE/TRUNCATE to be refused.

The overlay routes **only the test MCP server** through a fault proxy. It can return three HTTP 503 responses for
one Observation read, or let HAPI commit a Flag and close the connection before returning its response. All other
traffic is forwarded to real HAPI. No production code imports the proxy, and normal `docker-compose.yml` is unchanged.
The WSO2 test image adds pytest to the pinned server's existing venv and keeps uid 10001 and the original networks.

## Run on an isolated project

Use a disposable project named `afya-e8-2-*`, never the normal data-bearing stack. The runner refuses a different
project prefix or a missing test-proxy handshake. Keep the normal `.env` configured, set the model off, and enable
demo mode for synthetic fixtures. Only the web UI is published, on localhost:3000; stop another UI using that port
before starting this separate project.

From the repository root, PowerShell:

```powershell
function dc { docker compose -p afya-e8-2-check -f docker-compose.yml -f evals/stack/compose.yml @args }
New-Item -ItemType Directory -Force .playwright-mcp/group-a | Out-Null
$env:MODEL_ENABLED = '0'
$env:DEMO_MODE = '1'
$env:GROUP_A_COMMIT = 'uncommitted' # CI supplies the exact commit SHA
dc --profile web --profile checks up -d --build web fhir-fault
dc --profile checks build group-a
dc --profile checks run --rm --no-deps group-a
$env:GROUP_A_HAPI_IP = docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' (dc ps -q hapi)
dc exec -T -e GROUP_A_HAPI_IP wso2-fhir-mcp python -m pytest /checks/test_isolation.py -q -p no:cacheprovider --junitxml=/tmp/isolation.xml
dc cp wso2-fhir-mcp:/tmp/isolation.xml .playwright-mcp/group-a/isolation.xml
Push-Location web
npm.cmd ci
npx.cmd playwright install chromium
npm.cmd run test:group-a
Pop-Location
```

On Linux/CI, first run `mkdir -p .playwright-mcp/group-a` as the host runner user so Docker does not create a
root-owned artifact directory. Use `COMPOSE_PROJECT_NAME=afya-e8-2-ci` and
`COMPOSE_FILE=docker-compose.yml:evals/stack/compose.yml` with the same `docker compose` commands. Before the
WSO2-container pytest call, export its target IP:

```sh
export GROUP_A_HAPI_IP="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$(docker compose ps -q hapi)")"
```

Then `cd web && npm ci && npx playwright install --with-deps chromium && npm run test:group-a`.
The dedicated GitHub Actions `group-a` job runs that complete path, uploads the evidence, then removes its own
disposable project. Local cleanup, **only for this isolated project**: `dc --profile web --profile checks down --volumes`.

## Acceptance coverage

| Backlog case | Real-stack pytest evidence |
|---|---|
| Stable, B to B2 small rise, M1 to M2 mixed change | `test_fixed_cases` named parameters; no proposal/Flag/command/priority change |
| Improvement, no downgrade | `test_fixed_cases[improvement]`; confirmed ORANGE retained |
| Colour rise, confusion sign | `test_fixed_cases[colour rise/confused sign]`; pending proposal only |
| First visit, child outside chart | `test_unconfirmed_first_visit_and_child`; baseline-only and no-chart paths |
| HR 400 / Fahrenheit error | `test_impossible_input_saves_nothing`; real HAPI has no saved Observation |
| Missing value | `test_fixed_cases[missing mobility]`; current code accepts partial data with missing input/lower bound |
| Manager 403, double click 409 | `test_manager_403_nurse_approval_double_click_409_and_gated_write`; two simultaneous HTTP approvals yield one 200/one 409 |
| Expired/stale command, reused command | `test_expired_and_stale_commands_cannot_write`; successful command replay returns already_done, one Flag |
| Duplicate trigger | `test_model_outage_still_proposes_and_duplicate_run_does_not_duplicate`; real checkpoint replay and SQL dedup |
| Write through borrowed WSO2 | `test_actual_wso2_create_is_blocked_by_gateway`; actual create tool returns an error and no Patient exists |
| WSO2 cannot reach HAPI directly | `test_isolation.py`, executed inside the actual WSO2 server container; both DNS and direct-IP connection are refused while gateway metadata proves HAPI is live |
| `..;`, encoded dots, plain/encoded dollar operation | `test_raw_path_bypasses_are_refused_before_hapi`; raw HTTP preserves attack paths |
| Batch Bundle, method-override headers | `test_batch_bundle_and_method_override_cannot_write`; POST denied, GET cannot delete the actual Observation |
| Forged model write tool | `test_forged_model_write_tool_is_refused_by_real_toolnode`; rejected ToolMessage, audited refusal, zero clinical writes |
| Lost Flag response | `test_lost_flag_response_retry_converges_to_one_flag`; HAPI committed before disconnect; retry/reuse gives one Flag and one completion audit |
| FHIR down, retries and warning | `test_fhir_outage_retries_three_times_warns_and_resumes`; three observed wire failures, agent_failed notice, checkpoint resumes |
| Model down still proposes | Disabled-model cases and a simulated connection error at the scripted model boundary; ORANGE proposal with model_unavailable |
| Audit INSERT / UPDATE / DELETE / TRUNCATE | `test_audit_log_insert_allowed_but_mutations_denied` as the actual afya_app role |
| Unreviewed superseded proposal | `test_unreviewed_superseded_proposal_stays_visible_until_acknowledged` via real HTTP |

There are 25 main pytest cases plus 3 WSO2-container isolation cases, with no skips. JUnit reports include the
commit marker and service/model provenance. A run marked `uncommitted` or `+dirty` is local evidence, not proof
of a different revision; CI records its exact `github.sha`.

The suite exposed an encoded-dollar bypass (`%24everything` returned 200). The nginx raw-path deny-list now blocks
`%24` before HAPI; the regression expects 403. This addresses the `%24` item already listed under Mahdi's E12-3,
without claiming the other E12-3 fixes are done. Test observers send `Cache-Control: no-cache`: a demonstrated HAPI
search cache otherwise hid a newly committed Flag and produced a false failure.

## Browser evidence

`web/playwright.group-a.config.ts` runs the same real P-014 workflow in desktop Chromium and iPhone 13 browser
emulation using Chromium. This is responsive browser emulation, not a physical-phone/native-app claim. The tests
check keyboard focus, manager read-only controls and real API refusal, six nurse approval gates, YELLOW before
confirmation, ORANGE afterwards, document overflow and browser exceptions. Viewport screenshots use CSS-pixel scale
and focus on pending, manager-refused, nurse-confirmed and confirmed-ORANGE states.

Reports and screenshots live under `.playwright-mcp/group-a/` (git-ignored), and CI uploads `group-a-evidence`.
Inspect both desktop and mobile screenshots before handoff. No synthetic test results are presented as live-model
performance or clinical validation; these checks cover only the listed prototype behaviors.
