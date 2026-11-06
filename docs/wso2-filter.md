# WSO2 evidence projection (E2-4)

The borrowed server stays pinned to the digest in `docker-compose.yml` (installed package 0.11.0).
Its native `search` and `read` tools support the per-call `response_filter_fhirpaths` argument; this is not an
environment-variable setting. See the [upstream server](https://github.com/wso2/fhir-mcp-server) and the pinned
image's `/app/src/fhir_mcp_server/{server.py,field_filter/response_filter.py,field_filter/fhirpath_field_extractor.py}`.

`api/afya_api/fhir_projection.py` defines the FHIRPaths. `McpGateway.wso2` always supplies them, replacing any
caller-provided projection. Only Observation `search`/`read` are accepted. The same gateway is used by the API
and the host eval runner. No new tool is offered to the model.

The native response retains the reading ID, resource type, timestamp, panel code, and numeric values plus their
LOINC/UCUM codes. The encounter reference is retained internally to check visit ownership. Notes, narrative,
identifiers, subject/display text, categorical free text, quantity `unit` display strings, extensions, Bundle
links and unrelated components are not selected. The investigate tool output still contains only
`{id, time, values: [{code, value, unit}]}`; its unit is an allow-listed UCUM code, never the display string.

## Pinned-build behavior

- Projection keys are dotted expressions, not reconstructed FHIR objects. Filtered search entries are flattened.
  The adapter restores the minimal nested shape expected by the existing tool wrappers.
- Quantities are selected separately by LOINC code. Parallel arrays across all components could associate a
  value with the wrong code when another component is missing a field. Ambiguous duplicate components are omitted.
- In real MCP responses, projected decimal numbers arrive as strings such as `"38.7"`. The adapter accepts only
  bounded JSON-number strings and finite numbers. Text, booleans, non-finite and ambiguous values are omitted.
- Empty searches may omit `entry`. Invalid projections and FHIRPath evaluation errors fail closed with a generic
  tool error; no fallback retries an unfiltered request. The fixed-code proposal path remains unchanged.
- Native filtering is response minimisation inside the borrowed server, not a replacement for access control.
  WSO2 still fetches FHIR through the GET-only nginx gateway; the existing final model-side sanitizer stays in place.

## Repeatable live verification

The CI e2e job runs `scripts/verify_wso2.py` against real WSO2, nginx, HAPI and Postgres. It seeds two synthetic
visits and three observations, with markers in notes, narrative, display text, quantity unit text and extensions.
It checks raw native responses as well as the actual investigate wrappers, exact code/value/unit associations,
same-visit evidence, foreign-visit refusal, empty search and the client write-tool refusal. The WSO2-container check
verifies its gateway URL, demo auth setting, inability to resolve HAPI directly, and nginx rejection of all write
methods. It calls no model and never approves a proposal. Verification visits are finished afterwards.

With the stack running, from the repository root (POSIX shell):

```sh
export WSO2_CHECK_FIXTURE="$(docker compose exec -T afya-mcp python - seed < scripts/verify_wso2.py)"
docker compose exec -T -e WSO2_CHECK_FIXTURE api python - check < scripts/verify_wso2.py
docker compose exec -T wso2-fhir-mcp python - isolation < scripts/verify_wso2.py
docker compose exec -T -e WSO2_CHECK_FIXTURE afya-mcp python - finish < scripts/verify_wso2.py
```

Use `docker compose -p <isolated-test-project>` consistently when testing in a separate Compose project.
The compose file publishes no WSO2 port, keeps its two networks internal, and sets
`FHIR_SERVER_DISABLE_AUTHORIZATION=True` only for this private prototype setup; this task does not change auth
or network policy. These are synthetic-data integration checks, not clinical evaluation.
