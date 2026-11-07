# afya-mcp after the E13-1 / E13-2 migration (mcp SDK 2.3.0)

Informational comparison with [baseline-2025-11-25.md](baseline-2025-11-25.md). The authoritative run on the target
revision, with authorization, is E13-4's final phase (not done here). Not a clinical validation, not AAIF certification.

## 1. Same tool, older protocol path (2025-11-25 handshake)

Tool `@modelcontextprotocol/conformance` 0.1.16, same command and wrapper as the baseline, server now on `mcp==2.3.0`.
Result per mount (`/read`, `/act`, `/ui` identical): **9 passed, 23 failed** (baseline 8 passed, 24 failed). The only
difference is `dns-rebinding-protection`, now passing: the server accepts a valid loopback Origin (allowed origins are
configured) and still rejects a foreign Host (421) and a foreign Origin (403). Every other failure is unchanged
and is the same "reference fixture or feature not offered" list as in the baseline, not a pass. The two vacuous passes
(`tools-call-simple-text`, `tools-call-error`) remain vacuous.

## 2. Informational, target revision 2026-07-28 (alpha tool, NOT the final run)

`@modelcontextprotocol/conformance` 0.2.0-alpha.12 (npm `alpha` tag; the stable 0.1.16 has no 2026-07-28 scenarios),
`--spec-version 2026-07-28`, `/read/mcp`: 94 checks passed, 32 failed. Passing includes `tools-list`,
`resources-list`, `prompts-list`, `dns-rebinding-protection`, `caching` (7/7), `sep-2164-resource-not-found` (4/4) and
the input-required scenarios that do not need a fixture. Failures are of three kinds:

- reference fixtures this server does not have (test tools, prompts, resources, progress, image/audio content, JSON
  Schema tool, input-required sampling/elicitation/roots flows): not offered, not passes;
- `sep-2243-*` custom-header validation: not testable, the server has no tool with `x-mcp-header` annotations;
- two to look at in the final phase: `server-stateless` `sep-2575-server-rejects-undeclared-capability` (fixture tool
  absent, so likely not testable) and `http-header-validation` `sep-2243-server-accepts-whitespace-header-value`
  (HTTP 400, "mcp-name header does not match", probably also the missing fixture tool).

An alpha tool is not a pinned final tool: rerun with the then-current release in the final phase.
