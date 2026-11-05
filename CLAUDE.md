# CLAUDE.md: Afya Triage Watch

Instructions for AI coding assistants working in this repository. Read this first, then `docs/Afya_Tasks_BMAD.md`.

## What this is

Decision support for triage nurses in busy public outpatient departments (African Agentic AI Challenge, Healthcare
track "The Triage Desk", sub-theme *Deterioration Watch*). An agent watches the waiting room, re-scores patients
with the South African Triage Scale (SATS), and **proposes** a second look, citing the exact readings.
**A nurse or clinician confirms every change. The agent never diagnoses, prescribes, or moves a patient.**

Architecture: `docs/architecture-v4.1.pdf` (final). UI spec: `docs/web-design.md`. API contract: `docs/api.md`.

## Repository map

| Path | What |
|---|---|
| `docker-compose.yml` | Whole stack, one command. Only the UI is published (`127.0.0.1:3000`). |
| `gateway/nginx.conf` | GET-only gateway between the borrowed WSO2 FHIR MCP server and HAPI. |
| `db/` | `init.sh` (roles) + `schema.sql` (schema `afya`, append-only `audit_log`). Runs in `db-init`. |
| `rules/` | SATS chart YAML (`charts/`), plausibility limits. **Data, not code.** `rules/charts/` is outside the MIT licence. |
| `mcp/afya_mcp/` | Our MCP server: `rules.py` (scoring, triggers), `fhir.py` (FHIR client + mapping), `services.py` (tool logic), `server.py` (MCP mounts `/read/mcp`, `/act/mcp`). |
| `mcp/tests/` | pytest; `fake_fhir.py` is an in-memory FHIR store. |
| `api/afya_api/` | FastAPI + LangGraph agent (in progress). `lg_setup.py` creates checkpoint tables. |
| `web/` | Next.js nurse UI (brother). |
| `docs/` | Backlog, architecture, API contract, UI spec. |

## Commands

```bash
# tests and lint for the MCP server
cd mcp && pip install -e ".[dev]" && pytest && ruff check afya_mcp tests

# whole stack
cp .env.example .env            # set every CHANGE_ME
ollama pull qwen3:8b            # model runs on the host GPU
docker compose up --build       # add --profile web once web/ has its Dockerfile
```

## Rules for every change

### Workflow
- **The backlog is `docs/Afya_Tasks_BMAD.md` and nowhere else.** No GitHub issues, projects or milestones.
  When you finish or change a story, update its status (`[ ]` `[~]` `[x]` `[!]`), its Notes and the progress line
  in the same commit. Record decisions in its Decisions log.
- **Scope is frozen.** Do not add features that are not in the backlog. Ideas go to the backlog's Parking lot.
- **Commits:** plain messages, authored by the human committer only. **Never add `Co-Authored-By`, `Claude-Session`,
  "Generated with …" or any AI attribution** to commits or pull requests.
- Never rewrite published history or force-push without the repo owner's explicit permission.
- Never misrepresent when work was done: no backdated commits, no edited timestamps.

### Safety invariants (never break these)
- Scores, colours and triggers are computed by **fixed code** (`rules.py`), never by the LLM.
- Tools take **record IDs**, never vital-sign numbers copied by the model.
- The model can **add** urgency, never remove it. A colour rise always becomes a proposal.
- Nothing changes a patient's colour or queue position until a nurse or clinician confirms it.
- Write tools are never offered to the model. The borrowed WSO2 server is read-only (GET-only gateway).
- Every action is logged in `audit_log`; the app role can only INSERT/SELECT it.
- Never send FHIR free text (notes, names) to the model. Render patient quotes as plain text only.
- **Synthetic data only.** Never use real patient data. OpenRouter (frontier/remote models) only on synthetic fixtures,
  and off by default (`ALLOW_REMOTE_MODEL=false`).

### Wording (README, UI, pitch, code comments)
- Say: decision support for trained triage staff · flags patients for a second look · proposes, a nurse confirms ·
  cites the readings behind every flag · reminds the clinician on duty · research prototype on synthetic data.
- Never say: diagnoses · detects sepsis · predicts · AI triage · decides or prioritises patients ·
  automatically escalates or moves · replaces nurses · safe · accurate · validated · "not a medical device".

### Technical conventions
- Python 3.12, ruff (E, F, I; line length 120), pytest. Keep tool logic in `services.py`, transport in `server.py`.
- MCP Python SDK pinned to `mcp>=1.9,<2` (v2 renamed FastMCP).
- One reading = one FHIR Observation (LOINC 85353-1 panel with components); conditional create on
  `urn:afya:req|<idempotency key>`. Confirmed colour lives on `Encounter.priority` (system `urn:afya:sats-colour`).
- SATS values come only from `rules/charts/sats_adult_2012.yaml` (verified against the EMSSA SATS Training Manual 2012).
  Do not copy manual text into the repo.
- Model: `qwen3:8b` via Ollama with `think:false` and `num_ctx` 8192; backup `qwen3:4b-instruct`
  (plain `qwen3:4b` always thinks).
- Secrets only in `.env` (git-ignored). Never commit keys, tokens or real names of patients or staff.

## Team

Two people: Mahdi (agent core: rules, MCP tools, LangGraph, evals) and his brother (UI, infrastructure, Postgres setup,
synthetic patients, security tests, submission material). Owners per story are in the backlog.
