# Afya Triage Watch

Decision support for trained triage staff in busy public outpatient departments. An agent watches the waiting
room, notices patients who may be getting worse or are overdue for a re-check, and proposes a **second look**,
citing the exact readings behind every flag. **A nurse or clinician confirms every change; the agent never
diagnoses, prescribes or moves a patient.**

African Agentic AI Challenge · Healthcare track "The Triage Desk" · sub-theme *Deterioration Watch*.
Research prototype on synthetic data. Not clinically validated; not assessed or cleared as a medical device.

> Status: in development. Architecture: [`docs/architecture-v4.1.pdf`](docs/architecture-v4.1.pdf) ·
> backlog: [`docs/Afya_Tasks_BMAD.md`](docs/Afya_Tasks_BMAD.md)

## Run

```bash
cp .env.example .env          # set every CHANGE_ME
ollama pull qwen3:8b          # model runs on the host GPU via Ollama
docker compose up --build     # add --profile web once the UI is in
```

Only the nurse UI is published, on `http://127.0.0.1:3000`. Hardware: 16 GB RAM or more; a GPU is optional
(CPU-only Ollama: `docker compose --profile ollama up`, much slower).

## How it works (short)

| Part | Role |
|---|---|
| `mcp/` afya-mcp (ours) | 6 MCP tools: SATS scoring and queue reads; gated actions behind a separate mount |
| WSO2 FHIR MCP (borrowed, Apache-2.0) | lets the agent read standard FHIR health records; reaches HAPI only through a GET-only gateway |
| `api/` FastAPI + LangGraph | fixed code scores and decides triggers; the model maps warning signs and investigates with read-only tools; a watch loop sends reminders |
| `db/` PostgreSQL 16 | proposals, single-use commands, agent checkpoints, append-only audit log |
| `rules/` | SATS chart data (see licence note) |
| `web/` Next.js | nurse dashboard and approval card |

## Tests

```bash
cd mcp && pip install -e ".[dev]" && pytest
```

## Known gaps (stated honestly)

- Demo sign-in only ("sign in as…"); production needs proper sign-in (OIDC).
- The local FHIR store is unauthenticated and reachable only on private Docker networks.
- Adult SATS chart only; child charts are not included yet.
- Plausibility limits are provisional until reviewed with a triage nurse (`FIELD_NOTES.md`).

## Licence

Code: MIT (see `LICENSE`). `rules/charts/` is **not** covered by MIT: it holds SATS score bands transcribed from
the EMSSA SATS Training Manual (2012); see [`rules/charts/NOTICE.md`](rules/charts/NOTICE.md).
