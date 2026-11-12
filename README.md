# Afya Triage Watch

Decision support for trained triage staff in busy public outpatient departments. An agent watches the waiting
room, notices patients who may be getting worse or are overdue for a re-check, and proposes a **second look**,
citing the exact readings behind every flag. **A nurse or clinician confirms every change; the agent never
diagnoses, prescribes or moves a patient.**

African Agentic AI Challenge · Healthcare track "The Triage Desk" · sub-theme *Deterioration Watch*.
Research prototype on synthetic data. Not clinically validated; not assessed or cleared as a medical device.

> Status: research prototype, in development. Architecture: [`docs/architecture-v4.1.pdf`](docs/architecture-v4.1.pdf) · one page: [`ARCHITECTURE.md`](ARCHITECTURE.md) (details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)) · evals: [`EVALS.md`](EVALS.md) ·
> backlog: [`docs/Afya_Tasks_BMAD.md`](docs/Afya_Tasks_BMAD.md)

## Run

Needs Docker with Compose v2 and `openssl`. One command:

```bash
make demo          # or: sh scripts/demo.sh
```

It creates `.env` from `.env.example` with a fresh random value for every `CHANGE_ME` (an existing `.env` is kept),
builds and starts the whole stack in the background, and loads the 20 synthetic patients. Then open the nurse UI,
the only published port: `http://127.0.0.1:3000` (set `WEB_PORT` to change it). Stop with
`docker compose --profile web down`; the data stays in Docker volumes.

No model key is needed to try it: without one the agent proposes from the fixed SATS rules and each card says
"no model". To use the open-weights model, put a free Groq key in `.env` (`MODEL_PROVIDER=groq`,
`GROQ_API_KEY=...`, see [Model provider](#model-provider)) and run `make demo` again. Hardware: 8 GB RAM is enough
with a hosted model; a local model needs 16 GB or more.

By hand, the same steps are: `cp .env.example .env` and set every `CHANGE_ME` (see below), then
`docker compose --profile web up --build`, then the seed command below. Without `--profile web` the stack starts but
nothing is published.

### Load the synthetic waiting room

`make demo` already does this. By hand, with `DEMO_MODE=1` and `DATA_CLASSIFICATION=synthetic`, run:

```sh
docker compose --profile seed run --build --rm seed
```

This loads the 20 invented E5-1 patients and their first readings. Rerunning preserves
existing visits, arrival times and staff decisions without duplicating resources.
It does not run the model or approve proposals. Later evaluation readings remain in
the fixtures. See [`seed/README.md`](seed/README.md) for retry behaviour and review limits.

### `.env` values

| Variable | What |
|---|---|
| `PG_SUPERUSER_PASSWORD`, `AFYA_OWNER_PASSWORD`, `AFYA_APP_PASSWORD` | database passwords, URL-safe: `openssl rand -hex 24` |
| `SESSION_SECRET` | long random string that signs the session cookie |
| `AFYA_MCP_CLIENT_SECRET` | OAuth client secret of the api at the local authorization server (`openssl rand -hex 32`); the api trades it for short-lived access tokens to our MCP server (see below) |
| `MODEL_PROVIDER` | which provider runs the open-weights model: `ollama_cloud` (default), `groq`, `openrouter` or `ollama` (see next section) |
| `OLLAMA_API_KEY` | only with `MODEL_PROVIDER=ollama_cloud`; empty means rules only |
| `GROQ_API_KEY` | only with `MODEL_PROVIDER=groq`; empty means rules only |
| `OPENROUTER_API_KEY` | only with `MODEL_PROVIDER=openrouter`; empty means rules only |
| `DATA_CLASSIFICATION` | `synthetic` (default, the only value that allows the hosted model) |

`.env` is git-ignored and holds the only copies of these secrets. Never commit it.

### MCP authorization (OAuth 2.1)

Our MCP server accepts only OAuth 2.1 access tokens (MCP authorization profile, protocol 2026-07-28). `docker compose up`
also starts the authorization server, Authelia (`auth`, about 60 MB RAM), on an internal network over HTTPS with a local
CA; a one-shot `auth-init` creates the CA, keys and internal secrets in the `authdata` volume and registers the api's
client with a hash of `AFYA_MCP_CLIENT_SECRET`. Nothing else to configure. The api gets one short-lived token per MCP
mount with only that mount's scope (`afya:read`, `afya:act`, `afya:ui`). Rotate all of it with
`docker compose down && docker volume rm afya_authdata afya_authca afya_mcptls`. Design and limits: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). MCP application checks and raw official diagnostics (alpha tool, protocol 2026-07-28; no active protocol-failure waiver, not full conformance or certification): [`docs/conformance/README.md`](docs/conformance/README.md).

### Migrating an older checkout

Remove the obsolete `AFYA_MCP_TOKEN` from your local `.env` and set a fresh, random `AFYA_MCP_CLIENT_SECRET`. Use the updated Compose services, including `auth-init` and `auth`; the API and Group A runner discover the issuer, trust its mounted CA and request scoped tokens automatically. Do not paste an access token into tests or browser configuration. The borrowed WSO2 read connection keeps its legacy transport and never receives these credentials.

If an authorization server already exists and you change the client secret, refresh its hash and reload both services (keep the same Compose project and environment file):

```sh
docker compose run --rm --no-deps auth-init
docker compose restart auth
docker compose up -d --no-deps --force-recreate api
```

The existing CA and signing key stay in their volumes. The API obtains new short-lived tokens automatically.

The protected MCP connections now use certificate-verified HTTPS (`https://afya-mcp:9000`), as does the authorization server. `auth-init` creates the separate `mcptls` volume for the MCP private key; the API and test runner only receive the public CA. See the [requirement applicability review](docs/conformance/applicability.md). The web demo switcher remains separate from service OAuth. Staff can sign out from the user menu; managers have no demo scenario controls.

When upgrading an existing HTTP-based stack, recreate the authorization server, MCP and API so the HTTPS resource audiences, certificate and client configuration take effect together (keep your existing Compose project and `.env`):

```sh
docker compose --profile web up -d --build --force-recreate auth afya-mcp api web
```

Old access tokens name the HTTP audience and will be refused; the recreated API obtains new HTTPS-bound tokens. Existing data volumes are retained.

### Model provider

The model only maps warning signs from the nurse's free text and investigates with read-only tools; scores, colours and
triggers are fixed code, so the whole product works without a model (proposals then carry a "no model" notice).
The model is always open weights. Pick the provider with `MODEL_PROVIDER` in `.env`; each provider's model comes from
its own variable. All hosted providers get the same synthetic-data guard, key handling and limit handling.

| `MODEL_PROVIDER` | Where the model runs | Key | Notes |
|---|---|---|---|
| `ollama_cloud` (default) | Ollama's hosted API, `https://ollama.com/api` (native `/api/chat`) | `OLLAMA_API_KEY` | open-weights `gpt-oss:120b` by default (`OLLAMA_CLOUD_MODEL`, a name from `GET https://ollama.com/api/tags`). Account limits apply, see below. |
| `groq` | GroqCloud, OpenAI-compatible API, `https://api.groq.com/openai/v1` | `GROQ_API_KEY` | open-weights `openai/gpt-oss-120b` (Apache-2.0; `GROQ_MODEL`; backup `qwen/qwen3.8-27b`, Apache-2.0, a preview model on Groq). Free plan, no card; small limits, see below. Tool calling and strict JSON schema output. |
| `openrouter` | OpenRouter, provider pinned to `nebius/fp8`, no fallback | `OPENROUTER_API_KEY` | open-weights Qwen3-30B-A3B-Instruct-2507; billed cost of each call logged in the trace |
| `ollama` | your own Ollama (local or bridge address) | none | `MODEL=qwen3:8b`, see "Optional: local Ollama" |

- **Ollama Cloud setup.** Create a key at https://ollama.com/settings/keys and put it in `.env` as `OLLAMA_API_KEY`
  (it goes to the api container only and is sent only to ollama.com). List the models your account can use with
  `curl -s -H "Authorization: Bearer $OLLAMA_API_KEY" https://ollama.com/api/tags` and set `OLLAMA_CLOUD_MODEL` to one
  with tool calling. Ollama documents that its cloud does not support structured outputs, so the JSON schema goes
  into the prompt and the answer is checked by code (one retry, then rules only); `OLLAMA_CLOUD_FORMAT=1` sends
  `format` instead if that changes. For `gpt-oss` models thinking cannot be switched off, so `think` is `low`
  (`MODEL_THINK`) and the token limit per answer is 1024 (`MODEL_NUM_PREDICT`).
- **Ollama Cloud limits (caveat).** Plans, prices and limits change: check https://ollama.com/pricing and your usage
  at https://ollama.com/settings/usage. An account limit is answered with HTTP 429 or 402: the agent treats it as
  "model unavailable" (`rate_limited` / `usage_limit`), backs off with the circuit breaker and keeps proposing from
  the fixed rules with the `model_unavailable` notice. The api sends one cloud call at a time
  (`OLLAMA_CLOUD_CONCURRENCY`). The eval runner (`ollama_cloud:<name>` as the model) runs trials one after another
  and stops at the first limit without writing that trial as a result.
- **Groq setup.** Create a key at https://console.groq.com/keys and put it in `.env` as `GROQ_API_KEY`, with
  `MODEL_PROVIDER=groq` and `GROQ_MODEL=openai/gpt-oss-120b` (the key goes to the api container only and is sent only
  to api.groq.com, in the Authorization header). gpt-oss always reasons: `reasoning_effort` is `low`
  (`MODEL_REASONING_EFFORT`) and the token limit per answer is 1024 (`MODEL_NUM_PREDICT`). Groq rejects `top_k`, so it
  is not sent; `seed` is best effort on Groq. Cost on the free plan is 0; tokens and seconds are in the trace.
- **Groq free-plan limits (caveat).** For `openai/gpt-oss-120b`: 30 requests/minute, 1,000 requests/day, 8,000
  tokens/minute, 200,000 tokens/day (https://console.groq.com/docs/rate-limits; they change, check your account's
  limits page). One P-014 run uses about 2,000 tokens. The api sends one Groq call at a time (`GROQ_CONCURRENCY`),
  paces itself from Groq's `x-ratelimit-*` headers, and on HTTP 429 waits the `retry-after` only when it fits in the
  call's 60 s; otherwise the call ends as `rate_limited` (or `daily_limit` when the per-day limit is spent): "model
  unavailable", the circuit breaker backs off, and the proposal is still built from the fixed rules. The eval runner
  (`groq:<model id>`) runs trials one after another with a full per-minute budget each, retries a trial after a
  per-minute limit, stops cleanly at the daily limit (that trial is not written) and resumes with `RESUME=<batch>`.
- **Synthetic-data guard.** A hosted model (Ollama Cloud, Groq, OpenRouter, or an Ollama on a non-local address) is called
  only while `DATA_CLASSIFICATION=synthetic`, enforced in code. Any other value (or no key) refuses it and the agent continues on the fixed rules with the `model_unavailable` notice.
  This prototype holds synthetic patients only; a real deployment would run the same open-weights model hosted
  in-country.
- **Optional: local Ollama.** Set `MODEL_PROVIDER=ollama`, `MODEL=qwen3:8b` and `OLLAMA_BASE_URL=http://host.docker.internal:11434`,
  run `ollama pull qwen3:8b`, and make Ollama listen on the Docker bridge address only:
  `OLLAMA_HOST=172.17.0.1:11434 ollama serve`. **Never bind it to `0.0.0.0`** (that exposes it to the network). CPU-only
  Ollama in a container: `docker compose --profile ollama up` (much slower).

### Tests, lint, evals, smoke

```bash
# Python env with the three packages: pip install -e "mcp[dev]" -e "api[dev]" pytest ruff
eval "$(sh evals/stack_env.sh)"          # exports TEST_DATABASE_URL (the separate afya_test database), the stack URLs and the OAuth client settings
(cd mcp && pytest) && (cd api && pytest) && pytest evals/tests     # database tests skip when TEST_DATABASE_URL is unreachable
ruff check mcp api evals
make eval-test                           # statistics and metrics of the eval harness only
make eval MODELS=groq:openai/gpt-oss-120b RUNS=1   # live eval run (groq:<id>, ollama_cloud:<name>, OpenRouter ids or local Ollama tags), then rebuilds the tables in EVALS.md; see evals/README.md
scripts/smoke.sh                         # against the running stack; must end with SMOKE OK
```

Tests never touch the stack's `afya` database. Database tests use `afya_test`. The MCP authorization tests sign their own
tokens with a local test key: no authorization server or network is needed.

### Reset the demo database

`docker compose down -v` wipes everything (patients, proposals, audit log, agent checkpoints, HAPI data); then
`docker compose --profile web up --build` starts from empty. Details and a lighter reset: [`db/README.md`](db/README.md).

## How it works (short)

| Part | Role |
|---|---|
| `mcp/` afya-mcp (ours) | 6 MCP tools: SATS scoring and queue reads; gated actions behind a separate mount; OAuth 2.1 protected resource |
| `auth/` Authelia (Apache-2.0) | OAuth 2.1 authorization server for our MCP server (service client credentials, per-mount scopes) |
| WSO2 FHIR MCP (borrowed, Apache-2.0) | lets the agent read standard FHIR health records; reaches HAPI only through a GET-only gateway |
| `api/` FastAPI + LangGraph | fixed code scores and decides triggers; the model maps warning signs and investigates with read-only tools; a watch loop sends reminders |
| `db/` PostgreSQL 16 | proposals, single-use commands, agent checkpoints, append-only audit log |
| `rules/` | SATS chart data (see licence note) |
| `web/` Next.js | nurse dashboard and approval card |

## Scope and limitations

This is a research prototype built for a competition. The choices below keep it small, runnable on one laptop and
easy to audit; each one has a clear path to production.

| Area | In this prototype | For a real deployment |
|---|---|---|
| Sign-in | Demo users with a "sign in as…" switcher, every action logged with its user and role | Facility single sign-on (OIDC) |
| FHIR store | HAPI FHIR on a private Docker network, reachable only through our gateway and tools | The facility's FHIR server with authentication |
| Triage scale | SATS adult chart (patients over 12 years or over 150 cm); the chart registry is built for more | SATS child charts added as new chart files |
| Plausibility limits | Provisional values, to be reviewed with a practising triage nurse | Limits agreed with the facility's clinical lead |
| Data | Synthetic patients only | Real data only under the facility's governance and data-protection approvals |

## Licence

MIT (see `LICENSE`). `rules/charts/` holds SATS score bands transcribed from the EMSSA SATS Training Manual (2012),
used with EMSSA's permission; see [`rules/charts/NOTICE.md`](rules/charts/NOTICE.md).
