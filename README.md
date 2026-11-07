# Afya Triage Watch

Decision support for trained triage staff in busy public outpatient departments. An agent watches the waiting
room, notices patients who may be getting worse or are overdue for a re-check, and proposes a **second look**,
citing the exact readings behind every flag. **A nurse or clinician confirms every change; the agent never
diagnoses, prescribes or moves a patient.**

African Agentic AI Challenge · Healthcare track "The Triage Desk" · sub-theme *Deterioration Watch*.
Research prototype on synthetic data. Not clinically validated; not assessed or cleared as a medical device.

> Status: research prototype, in development. Architecture: [`docs/architecture-v4.1.pdf`](docs/architecture-v4.1.pdf) · one page: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · evals: [`EVALS.md`](EVALS.md) ·
> backlog: [`docs/Afya_Tasks_BMAD.md`](docs/Afya_Tasks_BMAD.md)

## Run

```bash
cp .env.example .env                       # then set every CHANGE_ME (see below)
docker compose --profile web up --build    # whole stack including the nurse UI
```

The nurse UI is the only published port: `http://127.0.0.1:3000` (add `-d` to run in the background). Without
`--profile web` the stack starts but nothing is published. Hardware: 8 GB RAM is enough with the default hosted
model; a local model needs 16 GB or more.

### `.env` values

| Variable | What |
|---|---|
| `PG_SUPERUSER_PASSWORD`, `AFYA_OWNER_PASSWORD`, `AFYA_APP_PASSWORD` | database passwords, URL-safe: `openssl rand -hex 24` |
| `SESSION_SECRET` | long random string that signs the session cookie |
| `AFYA_MCP_TOKEN` | bearer token the api sends to our MCP server, which refuses every call without it (`openssl rand -hex 24`) |
| `OPENROUTER_API_KEY` | optional; empty means rules only (see next section) |
| `DATA_CLASSIFICATION` | `synthetic` (default, the only value that allows the hosted model) |

`.env` is git-ignored and holds the only copies of these secrets. Never commit it.

### Model provider

The model only maps warning signs from the nurse's free text and investigates with read-only tools; scores, colours and
triggers are fixed code, so the whole product works without a model (proposals then carry a "no model" notice).

- **Default: OpenRouter**, open-weights Qwen3-30B-A3B-Instruct-2507 (`qwen/qwen3-30b-a3b-instruct-2507`), provider
  pinned to `nebius/fp8` with no fallback. Create a key at openrouter.ai, **set a spending limit on the key there**, and
  put it in `.env` as `OPENROUTER_API_KEY`. The billed cost of each call is logged in the agent trace.
- **Synthetic-data guard.** The hosted model is called only while `DATA_CLASSIFICATION=synthetic`, enforced in code. Any
  other value (or no key) refuses it and the agent continues on the fixed rules with the `model_unavailable` notice.
  This prototype holds synthetic patients only; a real deployment would run the same open-weights model hosted
  in-country.
- **Optional: local Ollama.** Set `MODEL_PROVIDER=ollama`, `MODEL=qwen3:8b` and `OLLAMA_BASE_URL=http://host.docker.internal:11434`,
  run `ollama pull qwen3:8b`, and make Ollama listen on the Docker bridge address only:
  `OLLAMA_HOST=172.17.0.1:11434 ollama serve`. **Never bind it to `0.0.0.0`** (that exposes it to the network). CPU-only
  Ollama in a container: `docker compose --profile ollama up` (much slower).

### Tests, lint, evals, smoke

```bash
# Python env with the three packages: pip install -e "mcp[dev]" -e "api[dev]" pytest ruff
eval "$(sh evals/stack_env.sh)"          # exports TEST_DATABASE_URL (the separate afya_test database) and the stack URLs
(cd mcp && pytest) && (cd api && pytest) && pytest evals/tests     # database tests skip when TEST_DATABASE_URL is unreachable
ruff check mcp api evals
make eval-test                           # statistics and metrics of the eval harness only
make eval MODELS=qwen/qwen3-30b-a3b-instruct-2507   # live eval run (needs the OpenRouter key; the default MODELS are local Ollama tags), then rebuilds the tables in EVALS.md; see evals/README.md
scripts/smoke.sh                         # against the running stack; must end with SMOKE OK
```

Tests never touch the stack's `afya` database. Database tests use `afya_test`.

### Reset the demo database

`docker compose down -v` wipes everything (patients, proposals, audit log, agent checkpoints, HAPI data); then
`docker compose --profile web up --build` starts from empty. Details and a lighter reset: [`db/README.md`](db/README.md).

## How it works (short)

| Part | Role |
|---|---|
| `mcp/` afya-mcp (ours) | 6 MCP tools: SATS scoring and queue reads; gated actions behind a separate mount |
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

Code: MIT (see `LICENSE`). `rules/charts/` is **not** covered by MIT: it holds SATS score bands transcribed from
the EMSSA SATS Training Manual (2012); see [`rules/charts/NOTICE.md`](rules/charts/NOTICE.md).
