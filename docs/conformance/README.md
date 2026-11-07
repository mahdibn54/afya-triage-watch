# MCP application checks and official diagnostic results

The current CI job is **MCP application regression checks**. A green job means the explicitly selected application assertions and the narrow known-error baseline have not regressed. It does **not** mean full MCP conformance, an SDK tier, AAIF certification or clinical validation.

## Why the old setup was misleading

The official suite is designed to exercise MCP implementations with purpose-built fixtures. Its [tool scenarios](https://github.com/modelcontextprotocol/conformance/blob/f44482ba17df816d3176962a11cdf36aec9bda00/src/scenarios/server/tools.ts) explicitly require example tools such as `test_simple_text` and image/audio tools. Afya does not offer those tools. A missing fixture can fail a scenario, or even accidentally satisfy a weak check with an Unknown tool error. Neither demonstrates successful execution of an Afya tool.

The full [frozen requirement set](https://github.com/modelcontextprotocol/conformance/blob/f44482ba17df816d3176962a11cdf36aec9bda00/requirements/2026-07-28.yaml) still runs unchanged. We do not edit it, relabel its failures as official skips, or claim that our custom profile satisfies it. See the upstream [SDK integration guide](https://github.com/modelcontextprotocol/conformance/blob/f44482ba17df816d3176962a11cdf36aec9bda00/SDK_INTEGRATION.md) and [requirements/baseline distinction](https://github.com/modelcontextprotocol/conformance/blob/f44482ba17df816d3176962a11cdf36aec9bda00/README.md#conformance-requirements).

The old schema-preservation failure was a **driver bug**, not demonstrated SDK data loss. The official [scenario contract](https://github.com/modelcontextprotocol/conformance/blob/f44482ba17df816d3176962a11cdf36aec9bda00/src/scenarios/client/json-schema-2020-12-preservation.ts) requires echoing the received schema verbatim. Our driver sent generated arguments containing an empty object. It now echoes the received `input_schema`; the scenario passes without changing SDK 2.3.0.

## What runs now

1. Run the full pinned official server suite against each real Afya mount and the full client suite against our SDK transport/provider driver, **without `--expected-failures`**. Keep all raw FAIL/WARN/SKIPPED outcomes.
2. Interpret those results using [application-profile.yaml](application-profile.yaml), our explicit application scope. `applicable` checks are gated. `fixture_dependent`, `not_offered` and `not_exercised` are reported as **NOT_ASSESSED**, never as passes or official exemptions.
3. Gate every wire-schema failure, including those inside fixture-dependent scenarios. Gate new failures inside selected scenarios, including the tested parts of `server-stateless`; only its two named diagnostic-tool checks are excluded.
4. Probe the actual tool catalogues and missing-required-argument rejection on all mounts. These are supplemental Afya checks, not official scenarios; no patient data, database or FHIR service is needed.
5. Probe unknown-prompt error handling. SDK 2.3.0 returns `-32603` instead of `-32602` on all three mounts. This is **one unresolved issue reproduced three times**, visibly `KNOWN_FAILURE`, not a pass. Only this exact error is baselined. Another failure or a newly passing result makes CI red until reviewed.
6. Write `application-report.json`, `.md` and `.html`; append the Markdown report to the GitHub Actions summary and upload all raw reports plus the offline-server log.

Missing/duplicate scenario output, unknown scenarios, missing excluded checks, incomplete probes, skipped-only applicable scenarios, invalid check statuses and unexpected failures make the application gate fail. Repeated check IDs inside one scenario are valid upstream behavior: every occurrence is assessed. Do not reuse a result directory between runs.

## Verified correction

Source before this correction: `ba48e3d`; protocol `2026-07-28`; official tool `@modelcontextprotocol/conformance@0.2.0-alpha.12`, source `f44482ba17df816d3176962a11cdf36aec9bda00`. All official raw commands exit **1**, correctly indicating that the full requirement set did not pass.

| Run | Raw PASS / WARN / FAIL | Selected application scenarios passed | Not assessed |
|---|---|---|---|
| Each server mount | 13 / 2 / 35 | 9 | 41 |
| Client SDK transport/provider driver | 9 / 0 / 30 | 9 | 30 |

The server's nine include `server-stateless` with two fixture-dependent checks excluded; 23 actual assertions remain in that scenario. These counts are a scoped application result, not a percentage of full conformance. Skipped assertions are never promoted to passes. Supplemental probes: 6 passes and 3 known failures for the single unknown-prompt issue.

The client driver uses the same SDK `Client`, HTTP transport, `MemoryTokens` and client-credentials provider class as the API. It does **not** exercise the whole `McpGateway`: configured issuer pinning, per-mount policy, WSO2 credential separation and JSON-result parsing remain application-test/smoke responsibilities. Browser OAuth, other service-auth methods, interactive inputs and unexercised resource/issuer tests remain disclosed coverage gaps, not proof of compliance. The official protocol server run uses an offline issuer and injected tokens; real OAuth protection remains covered by `mcp/tests/test_auth.py`, `api/tests/test_mcp_client.py` and `scripts/smoke.sh`.

The SDK still advertises empty prompt/resource capabilities. This remains a documented limitation rather than evidence that Afya serves prompt/resource fixtures. No production MCP, authentication, agent or clinical code was changed here. A future full SDK conformance exercise needs the upstream-required fixture adapter, kept outside the clinical tool catalogue.

## Verification of this setup

The 16 driver/report regression tests passed, including missing data, scope drift, global wire errors, a failure in the tested part of a partially excluded scenario, stale/changed SDK baselines, generic tool failures masquerading as validation failures and duplicate scenario directories. An end-to-end negative control changed a real tools-list assertion to FAILURE and made the report command exit 1. Related offline checks passed: 46 MCP authentication/discovery tests and 7 API MCP-client tests. The generated HTML summary and expanded decisions were checked in desktop and iPhone emulation; screenshots were inspected and page/table overflow checked. Ignored local evidence: `.playwright-mcp/conformance-corrected/`, `conformance-report-*.png` and `conformance-negative-control/`.

## Reproduce

Install `mcp[dev]` and `api[dev]`, Python 3.12 and Node 22. Use a **fresh** output directory:

```sh
python -m pytest scripts/tests/test_conformance_setup.py -q
PYTHONPATH=mcp python -m uvicorn conformance_app:app --app-dir scripts --port 9100 > conformance-server.log 2>&1 &
```

In a shell with the server ready:

```sh
for m in read act ui; do
  npx -y @modelcontextprotocol/conformance@0.2.0-alpha.12 server --url http://localhost:9100/$m/mcp \
    --requirements 2026-07-28 -o conformance-out/server-$m
  # Expected raw exit is 1: keep the failure output. Do not use shell `set -e` to stop before the report.
done
PYTHONPATH=api npx -y @modelcontextprotocol/conformance@0.2.0-alpha.12 client \
  --command "python scripts/conformance_client.py" --requirements 2026-07-28 -o conformance-out/client
python scripts/conformance_probe.py --output conformance-out/probes.json
python scripts/conformance_scope.py --root conformance-out --commit "$(git rev-parse HEAD)"
```

The last command is the **application regression gate**; it currently exits 0 with a visible warning about the known SDK error. The [CI job](ci-job.yaml) also checks tool execution failures and retains evidence when a step fails. The old [full-suite report](final-2026-07-28.md) and [historical failure waiver](historical-expected-failures.yaml) are historical only and no longer used by CI.
