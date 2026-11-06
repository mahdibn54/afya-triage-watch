# Afya Triage Watch: Project Backlog (BMAD style)

> **This file is the only backlog.** There are no GitHub issues. Every task, its status and its details live
> here. Update the story's status (and its notes, if needed) in the same pull request that does the work.

**Architecture:** v4.1, accepted ([`architecture-v4.1.pdf`](architecture-v4.1.pdf))
**Challenge:** African Agentic AI Challenge, Healthcare track "The Triage Desk", sub-theme *Deterioration Watch*
**Repo:** https://github.com/mahdibn54/afya-triage-watch
**Team:** **M** = Mahdi (agent core) · **B** = Brother (product, infra, data, proof)
**Deadlines:** code freeze **Day 10** · submission day (Nairobi) · jury the day after
**Budget:** $0, plus OpenRouter capped at $10–20

**Status:** `[ ]` to do · `[~]` in progress / drafted · `[x]` done · `[!]` blocked (say why in Notes)

**Progress:** 55 done · 9 drafted · 22 to do · 1 blocked · 87 stories

---

## How we work

1. Pick the next story for your name on the day board (bottom of this file). Check its dependencies are `[x]`.
2. **Claim it first:** `git pull`, set the story to `[~]`, commit and push, so the other person sees it is taken.
   Never start a story owned by the other person; if it blocks you, mark yours `[!]` and say why.
   Then create a branch named after the story: `E7-3-approval-card`.
3. Do the work, then meet the story's **Acceptance** bullets and the Definition of Done.
4. In the same PR, set the story's status to `[x]` here and add anything useful to its **Notes**.
5. The other person reviews; merge only when CI is green.
6. Daily 15-minute check-in: what's done, what's next, what's blocked (`[!]` + reason here).
7. Nothing new after **Day 8**. Late ideas go to "Parking lot" at the end.

## Who does what

Remaining estimate: **Mahdi ≈ 53 h** (light on Day 3–4 because of vaccines) · **Brother ≈ 50 h**.

| Mahdi: the agent core (explained in the live review) | Brother: product, infra, data and proof |
|---|---|
| SATS rules and scorer | Next.js nurse UI, approval card, notices, audit viewer, sign-in switcher (E7) |
| afya-mcp tools (E4); compose, networks, gateway, Postgres setup (E2-1…E2-3, E3-1…E3-4, done) | WSO2 response trimming, clean-machine test (E2-4, E2-7) |
| LangGraph agent: signs, investigate loop, watch loop, fallbacks (E5-2…E5-11) | |
| Approve/claim/sweep logic and write endpoints (E3-5, E3-6, E6-1b, E6-3, E6-4) | Read endpoints + demo session (E6-1a, E6-2), host Ollama setup (E2-5) |
| Eval harness, model runs, EVALS.md (E8-1, E8-3…E8-6) | 20 synthetic patients (E5-1), fixed-code/security tests (E8-2), secrets check (E8-7) |
| Nurse interview + FIELD_NOTES (E9) | README, 300-word text, video, deck (E10-1, E10-3…E10-5), seed job (E2-6) |
| UI data and demo endpoints (E6-5, E6-6) | Nurse UI per `web-design.md`: board, approval card with highlighted quotes and evidence, gate ticks, agent trace, demo loader (E7) |
| ARCHITECTURE.md, live-review rehearsals (E10-2, E11) | |

---

## Definition of Done (every story)

- [ ] Merged to `main` through a reviewed PR; CI green (ruff, mypy, pytest, `next build`).
- [ ] Every action is logged in `audit_log` (actor, inputs, outputs, time; model tokens and latency for model calls).
- [ ] Synthetic data only. No real patient data, ever.
- [ ] Nothing changes a patient's colour or queue position without a nurse or clinician confirming.
- [ ] README updated if run steps or env vars changed.
- [ ] Wording follows the say/avoid table (architecture §14): never "diagnose", "AI triage", "escalate", "safe", "validated".
- [ ] This file updated: status `[x]` and Notes.

---

## E0 · Setup and governance

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E0-1 | [x] | Public repo, MIT licence, README, `.gitignore`, `.env.example` | M | Day 1 | 0.5 h | – |
| E0-2 | [x] | SATS NOTICE and licence carve-out for `rules/charts/` | M | Day 1 | 0.5 h | E0-1 |
| E0-3 | [ ] | Send the email to EMSSA (draft at the end of this file) | M | Day 1 | 0.3 h | – |
| E0-4 | [ ] | Ask Clinton: exact submission time, format, brother listed as team member | M | Day 1 | 0.2 h | – |
| E0-5 | [~] | Agree the API contract | M+B | Day 1 | 1 h | – |
| E0-6 | [~] | CI on every push | B | Day 2 | 1 h | E0-1 |
| E0-7 | [x] | Invite brother as collaborator (`dhekerbenamor@gmail.com`) | M | Day 1 | 0.1 h | E0-1 |

**E0-1** · Files: `LICENSE`, `README.md`, `.gitignore`, `.env.example` · Acceptance: repo public; `.env` ignored. · Notes: done in commit `1645177`. Commits use mahdibenamor13@gmail.com.
**E0-2** · Files: `rules/charts/NOTICE.md`, licence line in `LICENSE` and `README.md` · Acceptance: chart folder explicitly outside MIT, EMSSA attributed, no manual text copied.
**E0-3** · Acceptance: email sent; reply (or none) recorded here. Until permission, the chart folder stays "non-commercial research only". · Notes: deferred by M for now.
**E0-4** · Acceptance: answers recorded here: deadline timestamp + timezone, required deliverables, team listing. · Notes: deferred by M for now.
**E0-5** · Files: `docs/api.md` · Acceptance: both agree; brother can build the UI against fake JSON matching it. · Notes: draft written Day 1. Rewritten by B against the code: conventions (IDs, times, error body, quote offsets), per-endpoint fields with 19 example JSON blocks (the UI's fixtures, P-014 numbers from `test_rules.py`), "backend today" status per endpoint, added `/demo/users`, `/proposals/{id}/acknowledge`, `/notifications/{id}/acknowledge`. Verified: every example recomputed with the real scorer, `evaluate_trigger`, `check_plausible` and `get_queue_state` (196 checks pass; this caught one wrong example, `no_chart` without a confirmed colour); audit payloads and gate times checked against the live Postgres through `workflow.py`; WSO2 tool names read from the live server. Also checked against `docs/architecture-v4.1.pdf` (sections 3–10, Appendix A and B): complaint limit, quote offsets on the original text, colour override (section 7), `submit_decision` actions and the sign verdict added to proposals. **M's answers (Day 8): all of Q1–Q13 accepted** as B proposed (marked in `docs/api.md` section 9). Q6 decision: the nurse or clinician may override the colour to ANY level, including lower than proposed, with a mandatory reason (audited); the agent itself still never proposes a downgrade. Backend work these answers need is in E6-1b/E6-3/E6-5 and the data layer. Status stays `[~]` until B confirms from the UI side.
**E0-6** · Files: `.github/workflows/ci.yml` · Acceptance: on push and PR runs `ruff`, `mypy`, `pytest` (mcp + api) and `npm run build` (web); red CI blocks merge. · Notes: `.github/workflows/ci.yml` added by B: ruff (mcp, api), pytest (mcp), web typecheck, lint, `next build`, fixtures-match-`docs/api.md` check and the Playwright P-014 test (E7-11) on the fake API. mypy runs but does not fail the build yet: 52 existing errors in `mcp/afya_mcp` (M's modules). Left: M fixes or accepts the mypy errors, then branch protection so a red CI blocks merge (repo owner setting).
**E0-7** · Acceptance: invitation accepted. · Notes: done: B has push access and commits to main.

---

## E1 · SATS rules and scoring (fixed code, no LLM)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E1-1 | [x] | Chart registry with the adult 2012 chart as YAML | M | Day 1 | 1.5 h | E0-2 |
| E1-2 | [x] | Sign allow-list (2 RED, 12 ORANGE, 5 YELLOW) with own glosses | M | Day 1 | 0.5 h | E1-1 |
| E1-3 | [x] | Chart selection by age/height; "no chart" otherwise | M | Day 2 | 1 h | E1-1 |
| E1-4 | [x] | Pure scorer `score(values, chart)` | M | Day 1 | 1.5 h | E1-1 |
| E1-5 | [x] | Plausibility limits in YAML (provisional) | M | Day 1 | 0.5 h | – |
| E1-6 | [x] | Trigger rule in code | M | Day 1 | 1 h | E1-4 |
| E1-7 | [x] | Fixture tests (11 patients from architecture §11) | M | Day 1 | 1 h | E1-4 |
| E1-8 | [x] | Band-edge tests from an independent reading of the chart | M | Day 1 | 1 h | E1-4 |

**E1-1** · Files: `rules/charts/sats_adult_2012.yaml` · Acceptance: bands, colours, target times; numbers match the EMSSA 2012 adult chart. · Notes: manual page references added Day 1 (`source_pages`: target times pp. 6–7, adult chart and signs p. 8, adult TEWS pp. 26–27).
**E1-2** · Acceptance: codes match the verified adult discriminator list (architecture §2); glosses are our own words.
**E1-3** · Files: `mcp/afya_mcp/rules.py` (`select_chart`) · Acceptance: adult = over 12 y or over 150 cm; otherwise `NoChartForPatient` → UI notice "no chart for this patient yet". · Notes: function + test done; wired into `compute_tews` (E4-3). Code review: unknown age and height → `NoChartForPatient`; age is calendar-exact around the 12th birthday (tests).
**E1-4** · Acceptance: returns tews, colour by TEWS, signs implied by inputs, final colour = highest of TEWS and signs, points and cited IDs per input; missing inputs reported, never guessed.
**E1-5** · Files: `rules/plausibility.yaml` · Acceptance: limits loaded by code; outside → nothing saved, re-measure notice. · Notes: `load_plausibility` + `check_plausible` done Day 1 with tests (HR 400, °F temperature, etc.); values provisional until reviewed with the nurse (E9-4). The "nothing saved" part is enforced in `record_vitals` (E4-2).
**E1-6** · Acceptance: proposal only on (a) colour rise, (b) current ORANGE/RED sign, (c) nurse-reported worsening; smaller changes logged only; never downgrades. Tests for B→B2, M1→M2, improvement, C (confused). · Notes: `evaluate_trigger` done Day 1: trigger reference is the colour a nurse last **confirmed**; urgent = ORANGE/RED signs only (a YELLOW sign alone is logged); incomplete scores still trigger and say "lower bound"; unknown sign codes raise. 20 tests in `mcp/tests/test_plausibility_trigger.py`. Code review: if no colour was ever confirmed, the previous reading is the reference (only the very first reading is a baseline), so a never-confirmed visit that worsens still gets a proposal; "lower bound" is also logged when nothing triggers.
**E1-7 / E1-8** · Files: `mcp/tests/test_rules.py` · Notes: 44 tests passing on Day 1 (64 in total with E1-5/E1-6). Code review added decimal edges, case, NaN and TEWS→colour tests. Chart fix: every AVPU level below alert (voice, pain, unresponsive) now implies the ORANGE reduced-consciousness sign, not only "confused" — to re-check against manual p. 8.

---

## E2 · Infrastructure (one command)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E2-1 | [x] | docker-compose with all services and health checks | M | Day 2 | 3 h | E0-5 |
| E2-2 | [x] | Private networks; only the UI published on 127.0.0.1:3000 | M | Day 2 | 1 h | E2-1 |
| E2-3 | [x] | nginx gateway, GET only | M | Day 5 | 1 h | E2-2 |
| E2-4 | [~] | WSO2 config and FHIRPath response trimming | B | Day 5 | 1 h | E2-2 |
| E2-5 | [ ] | Host Ollama for the GPU, bound to the Docker bridge | B | Day 2 | 0.5 h | – |
| E2-6 | [ ] | Seed job loading the 20 synthetic patients into HAPI | B | Day 4 | 1 h | E5-1 |
| E2-7 | [ ] | Clean-machine test | B | Day 10 | 1 h | all |

**E2-1** · Files: `docker-compose.yml` · Acceptance: `docker compose up --build` starts postgres → db-init → lg-init → hapi → gateway → wso2-fhir-mcp → afya-mcp → api (→ web with `--profile web`) without manual steps. · Notes: drafted by M; verified and fixed by M on the first full run (`scripts/smoke.sh`, all checks pass). Fixes: (1) `ghcr.io/wso2/fhir-mcp-server:0.11.0` is not published, pinned by digest to `:latest` (0.11.0 build); (2) HAPI's default H2 is in-memory (`jdbc:h2:mem:test_mem`), so `/app/target` was wrong: the file DB is now `/data/h2/hapi` on volume `hapidata` via `spring.datasource.url`, and a one-shot `hapi-perms` chowns the volume to uid 65532 (distroless image); (3) postgres healthcheck over TCP (`-h 127.0.0.1`) plus `pg_isready` wait in `db/init.sh`; (4) `afya_app` search_path `afya, lg`. WSO2 MCP path `/mcp` confirmed. Measured: cold start with image pulls 5 min 24 s, with images cached 12 s to all containers up, HAPI answers after about 40 s more. Images: afya-api 268 MB, afya-mcp 193 MB, wso2 fhir-mcp 198 MB, hapi 582 MB, postgres 294 MB, nginx 48 MB. `docker stats --no-stream` RAM: hapi 1.14 GiB, wso2-fhir-mcp 61 MiB, postgres 26 MiB (54 MiB under load), afya-mcp 43 MiB, api 36 MiB, gateway 2 MiB; about 1.3 GiB total.
**E2-2** · Acceptance: networks `app`, `mcp`, `fhir_ro`, `fhir_rw` internal; only `web` published. Test: `docker compose exec wso2-fhir-mcp` cannot resolve `hapi`. · Notes: drafted by M; verified by M (smoke.sh: wso2-fhir-mcp cannot resolve `hapi`, reaches `gateway`; no host ports published without the web profile).
**E2-3** · Files: `gateway/nginx.conf` · Acceptance: GET/HEAD only; 403 for `;` `..` `%2e` `%2f` `%3b` `%5c` `$` in the path; method-override headers cleared; reference params like `subject=Patient%2F1` in the query still work. · Notes: `nginx -t` OK on Day 1. WSO2 0.11.0 uses GET for search and read (checked in its source). Verified by M on the live stack (smoke.sh): GET 200; POST/PUT/DELETE/PATCH 403; `;` `..` `%2e` `$` 403; `subject=Patient%2F1` query 200.
**E2-4** · Acceptance: WSO2 reaches HAPI only via `http://gateway/fhir`; `FHIR_SERVER_DISABLE_AUTHORIZATION=True` only on the private network; a FHIRPath filter returns id, code, value, unit, time. · Notes: M verified the first half (WSO2 reaches HAPI only via the gateway, MCP answers at `/mcp`, authorization disabled on the private network); FHIRPath trimming not checked yet.
**E2-5** · Acceptance: `ollama pull qwen3:8b qwen3:4b-instruct qwen3:30b-a3b`; `OLLAMA_HOST=172.17.0.1:11434` (Docker bridge, not 0.0.0.0); API reaches it via `host.docker.internal`. Record tokens/s here.
**E2-6** · Files: `seed/` · Acceptance: idempotent; loads the 20 patients and their visits into HAPI and `afya.visits`.
**E2-7** · Acceptance: fresh clone on another machine or user → README steps only → full P-014 demo works. Time it and note it here.

---

## E3 · PostgreSQL data layer

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E3-1 | [x] | db-init runs the schema as `afya_owner` | M | Day 5 | 1.5 h | E2-1 |
| E3-2 | [x] | Roles: `afya_app` least privilege | M | Day 5 | 0.5 h | E3-1 |
| E3-3 | [x] | Audit log append-only (grants + triggers) | M | Day 5 | 0.5 h | E3-1 |
| E3-4 | [x] | LangGraph checkpoints in schema `lg` | M | Day 5 | 0.5 h | E3-1 |
| E3-5 | [x] | Approve, claim, mark-done, startup-sweep queries | M | Day 7 | 2 h | E3-1 |
| E3-6 | [x] | Dedup key and insert | M | Day 8 | 1 h | E3-1 |

**E3-1** · Files: `db/init.sh`, `db/schema.sql` · Acceptance: runs on every start without errors (idempotent). · Notes: DDL written Day 1; verified by M on the first full run (db-init ran clean on a fresh volume and again on restart; idempotent). Audit fixes added later: `proposals_guard` trigger (decided proposals are immutable, only nurse/clinician can approve), partial indexes, inline `commands` CHECK; db-init re-run on the existing volume was clean. Re-verified by B on Windows: the first run failed (exit 2, `set: illegal option -`) because `core.autocrlf=true` checked `db/init.sh` out with CRLF line endings; fixed with `.gitattributes` (`* text=auto eol=lf`). After that, a fresh volume ran clean and a second `db-init` run exited 0 with no errors.
**E3-2** · Acceptance: `afya_app` is LOGIN, NOSUPERUSER, not a member of `afya_owner`, has no CREATE; owner and superuser passwords exist only in `db-init` and `lg-init`. · Notes: verified by M (no CREATE, not a member of owner; search_path `afya, lg` added in `db/init.sh`). DB audit fixes applied: `REVOKE TEMP` from PUBLIC, default privileges on sequences in `lg`; `afya_app` inserts into `audit_log` by column grant only (`id` and `at` always from defaults). Re-verified by B: `afya_app` is LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, has no role memberships and no CREATE on `afya`, `lg`, `public` or the database; TEMP denied. The owner password appears only in `db-init` and `lg-init`; the superuser password only in `db-init` and `postgres` (which needs it to initialise).
**E3-3** · Acceptance: as `afya_app`, UPDATE, DELETE and TRUNCATE on `afya.audit_log` all fail; INSERT works (identity column needs no sequence grant: confirm). Wording: "append-only for the application role". · Notes: verified by M in `scripts/smoke.sh`: INSERT works (no sequence grant needed), UPDATE/DELETE/TRUNCATE all fail. Column-level INSERT grant (no `id`/`at`), `nextval` denied, and indexes on `audit_log(visit_id, at)` and `(run_id)` added; the smoke test covers them. Re-verified by B as `afya_app`: INSERT works; UPDATE, DELETE, TRUNCATE and setting `at` are denied; an unknown actor is refused by the foreign key. Trigger layer tested as `afya_owner` (which has the grants): UPDATE, DELETE and TRUNCATE all raise "audit_log is append-only". `proposals_guard`: a manager approve is refused, a nurse approve updates 1 row then 0 rows, re-deciding is refused, and a duplicate `(visit_id, trigger, evidence_hash)` is refused.
**E3-4** · Files: `api/afya_api/lg_setup.py` · Acceptance: `lg-init` creates the checkpoint tables as owner; `afya_app` can read/write them but not alter them. · Notes: verified by M: `PostgresSaver.setup()` worked as is (no autocommit change needed); `afya_app` can insert/delete, ALTER fails. Re-verified by B: the 4 tables in `lg` are owned by `afya_owner`; `afya_app` has INSERT, SELECT, UPDATE and DELETE but not TRUNCATE; ALTER and DROP fail ("must be owner of table"); CREATE TABLE in `afya` and `lg` is denied.
**E3-5** · Acceptance: approve = role check (403) then `UPDATE … WHERE status='pending'` (0 rows → 409) + audit + command in **one transaction**; claim = not claimed, not expired, still the latest reading, proposal approved; resume = claimed, not done, attempts < 5; startup sweep resumes approved-not-done. SQL in architecture Appendix A. · Notes: `mcp/afya_mcp/workflow.py` (one function per query: `approve_proposal`, `claim_command`, `mark_done`, `resume_command`, `sweep_open_commands`, `acknowledge`) and `db.py` (connection with autocommit, dict rows, `prepare_threshold=0`). The api imports it as `afya_mcp.workflow`: `api/Dockerfile` now builds from the repo root and installs `mcp/` (compose `build.context: .`). Approve raises `Forbidden` (403) or `Conflict` (409) and audits both refusals; the command's colour comes from `proposal.payload['to_colour']`, expiry is one hour. Resume adds one attempt; the sweep returns approved, not-done commands with attempts < 5 (unclaimed ones only while unexpired). Tests: `mcp/tests/test_postgres_integration.py` (marked `integration`, skipped without `DATABASE_URL`; run with an `afya_app` URL to the Postgres container address) including two-connection races for double approve and double claim. Built by the lead's agent (owner stays M).
**E3-6** · Acceptance: `UNIQUE(visit_id, trigger, evidence_hash)`; hash = sorted obs IDs + sign codes + rules version (never the model's quote text); `INSERT … ON CONFLICT DO NOTHING RETURNING`. · Notes: `workflow.evidence_hash` (sha256 of sorted unique obs IDs, sorted sign codes, rules version; the caller passes the chart id as version) and `workflow.insert_proposal` (None on a duplicate; race test with two connections). `supersede_pending` marks older pending proposals superseded with `reviewed=false`; it runs inside `db.upsert_visit`, so newer vitals supersede in the same transaction as the `latest_obs_id` update. `acknowledge` sets `reviewed`. Open points closed with E4-6: `rules_version` in the hash is the chart_id (no separate version field); `insert_proposal` now refuses a payload without a valid `to_colour` (or with a malformed `cited_obs_ids`) with `ValueError` (test).

---

## E4 · afya-mcp server (6 tools)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E4-1 | [x] | Server with two mounts: `/read/mcp` and `/act/mcp` | M | Day 5 | 1 h | – |
| E4-2 | [x] | `record_vitals` | M | Day 5 | 2 h | E3-1 |
| E4-3 | [x] | `compute_tews` | M | Day 2 | 1 h | E1-4 |
| E4-4 | [x] | `check_deterioration` | M | Day 2 | 1.5 h | E4-3 |
| E4-5 | [x] | `get_queue_state` | M | Day 6 | 1.5 h | E3-1 |
| E4-6 | [x] | `raise_recheck_flag` via the executor registry | M | Day 7 | 2.5 h | E3-5 |
| E4-7 | [x] | `notify_staff` | M | Day 8 | 1 h | E3-1 |
| E4-8 | [x] | Audit every tool call | M | Day 5–8 | incl. | E3-3 |

**E4-1** · Files: `mcp/afya_mcp/server.py` · Acceptance: `/healthz` OK; read tools only on `/read/mcp`, act tools only on `/act/mcp`. · Notes: done Day 2; verified with Starlette TestClient (`/healthz` OK; read = compute_tews, check_deterioration, get_queue_state; act = record_vitals, raise_recheck_flag, notify_staff). **SDK pinned to `mcp<2`**: v2 renamed FastMCP to MCPServer. Code review: FastMCP's default DNS-rebinding check only accepted `Host: localhost`, so `http://afya-mcp:9000` got HTTP 421; allowed hosts now set (`AFYA_MCP_ALLOWED_HOSTS`, default `afya-mcp:*,localhost:*,127.0.0.1:*`) and tested. Tools are async and run the blocking FHIR client in a worker thread.
**E4-2** · Acceptance: input = LOINC-coded list + idempotency key; plausibility check first; FHIR conditional create with `identifier=urn:afya:req|<key>`; updates `visits.latest_obs_id` in the same transaction; retry returns the same IDs. · Notes: FHIR part done Day 2 (`services.record_vitals`: plausibility first, one Observation per reading with LOINC components, conditional create on `urn:afya:req|<key>`; tests prove a retry creates nothing new and HR 400 saves nothing). Code review: unknown inputs, unknown categorical values, empty entries, unsafe idempotency keys and a visit of another patient are rejected (`status: invalid`, nothing saved). **DB part done: after the FHIR write, `record_vitals` upserts `visits` (id, patient_id, latest_obs_id) through an injected `VisitStore` (`db.PgVisitStore`; fake in tests). The latest reading is read back from FHIR so a retry of an older entry cannot move `latest_obs_id` backwards; a database failure propagates and the retry converges. Smoke test covers it through `/act/mcp`. Audited since E4-8: the tool now takes `actor` (the nurse's user id) and an optional `run_id`.
**E4-3** · Acceptance: input = observation ID only; reads values from HAPI itself; selects the chart (E1-3); returns score, colour, chart_id and cited IDs. · Notes: done Day 2; age from `Patient.birthDate`, height from extension `urn:afya:height-cm`; a child returns `no_chart`. Code review: accepts `Observation/<id>` or `<id>` and refuses other types; readings with another unit (e.g. °F), another code or status `entered-in-error` return `not_usable` instead of being scored.
**E4-4** · Acceptance: compares with earlier scored readings; returns change, trigger type (E1-6) and cited records. · Notes: done Day 2; input is `visit_id`; confirmed colour read from `Encounter.priority` (system `urn:afya:sats-colour`); returns per-input point changes with the record before/after (feeds the evidence table, E7-4); FHIR errors raise `FhirUnavailable` for the agent's retry path. Code: `mcp/afya_mcp/fhir.py`, `services.py`; tests use an in-memory FHIR (`tests/fake_fhir.py`). Code review: FHIR 4xx now raise `FhirNotFound`/`FhirRejected` (no retry), 5xx/429/timeouts `FhirUnavailable`; search filters on `status` and `http://loinc.org|85353-1`; unknown `Encounter.priority` colours raise. 124 tests passing.
**E4-5** · Acceptance: minutes waited vs SATS target per patient; overdue re-checks (site intervals from E9-4, labelled "site rule"); unread proposals with age. · Notes: `services.get_queue_state` (read mount, no input; audited as `agent`). Waiting visits = FHIR Encounters in `arrived`/`triaged`/`in-progress` (first 100, `truncated` flag), listed by arrival time (no ranking). Lead decisions: minutes waited from `Encounter.period.start`; confirmed colour from `Encounter.priority`; SATS target from the patient's chart (`target_minutes`, new `rules.target_minutes`). Re-check: next reading due = last reading (or arrival) + `recheck_minutes[colour]` from the new `rules/site.yaml` (`source: provisional site rule, to review with nurse`; replaced by the nurse's values in E9-4); without a confirmed colour no interval is guessed, only the first reading is due on arrival. Proposals from Postgres (`workflow.open_proposals`): pending, plus superseded-not-reviewed, with age and `reminder_due` (RED after 1 min, ORANGE after 5, from architecture s. 4, in `site.yaml`). Output holds IDs, codes, times and numbers only. One Observation search and one cached Patient read per visit (fine for a demo room). Tests: `tests/test_queue_state.py`, integration test for `open_proposals`, smoke check against HAPI.
**E4-6** · Acceptance: input = command ID only; claim (E3-5) → FHIR conditional create Flag (identifier derived from the command) + Encounter priority → mark done + audit in one transaction; safe on retry or crash. · Notes: `services.raise_recheck_flag(command_id, actor, run_id?)` on the act mount, dispatching through `services.EXECUTORS` keyed by `commands.action_type` (only `recheck_flag` → `write_recheck_flag`; a new action is one entry + one function). Flow: session advisory lock on the command (a second executor gets `in_progress`; released on disconnect) → claim, or resume when already claimed and not done → FHIR conditional create Flag (identifier `urn:afya:command|<command_id>`, code `urn:afya:codes#second-look`, subject, encounter, `period.start` = claim time, one `urn:afya:evidence` extension per cited Observation: the command's reading + proposal `payload.cited_obs_ids`, plus the confirmed colour) → absolute set of `Encounter.priority` to the command's colour (other codings kept; no write when already set) → `mark_done` (done_at + `command_done` audit row, one transaction). The tool call itself is audited by E4-8. Actor must be the user who approved the proposal, or `agent`/`system` (sweep, retries); a manager is refused by the audit wrapper. Refusals return a reason (expired, newer vitals, proposal not approved, attempts exhausted). Integration tests (`tests/test_executor_integration.py`): retry after a simulated crash between the FHIR write and `mark_done` converges to ONE Flag (one create) and one `command_done`; FHIR down then retry; stale reading refused; wrong approver refused; locked command `in_progress`. Smoke: approve → `raise_recheck_flag` through `/act/mcp` twice (done, then `already_done`), exactly one Flag in HAPI, `Encounter.priority` ORANGE, audit rows present, manager refused. Known limit: the Encounter update is a plain PUT (no `If-Match` version check).
**E4-7** · Acceptance: fixed text only (restates an existing proposal's colour and cited IDs, or "vitals due"); never changes the queue; audited. · Notes: `services.notify_staff(kind, proposal_id?, visit_id?)` on the act mount, tool signature `notify_staff(kind, actor, proposal_id?, visit_id?, run_id?)`, audited by E4-8. Kinds: `vitals_due` (visit), `remeasure` (visit, optional proposal), `clinician_reminder` (pending proposal; a decided one gives `not_sent`), `model_unavailable` (optional visit). Fixed templates only: they fill in visit/proposal IDs, the proposal's `to_colour` and its cited Observation IDs, nothing else (no advice, no free text). Stored in the new `afya.notifications` table (`db/schema.sql`: id, at, kind, visit_id, proposal_id, target_role nurse/clinician, text, acknowledged_at; idempotent DDL; `afya_app` has SELECT/INSERT and UPDATE on `acknowledged_at` only) so the API/UI can poll and acknowledge them; no dedup (the watch loop decides when to remind). Invalid kinds/IDs or a proposal of another visit store nothing. Integration tests in `tests/test_executor_integration.py` (texts, refusals, grants); smoke sends one through `/act/mcp` and checks the row, the audit row and the column grant.
**E4-8** · Acceptance: every call writes inputs, outputs, actor, run_id and latency to `audit_log`. · Notes: `mcp/afya_mcp/audit.py` (`audit.call`, used by every tool in `server.py`): one row per call with kind = tool name, actor, auth, visit_id, run_id and payload = trimmed inputs, trimmed output or error, `latency_ms`, mount. Actor (lead decision): act tools take `actor` (a user id from `afya.users`: the nurse for `record_vitals`, the approving user for `raise_recheck_flag`, `agent`/`system` for automated calls) and an optional `run_id`; a manager or unknown id is refused before the tool runs and the refusal is audited (unknown ids as `system`, FK). Read tools take only an optional `run_id` and always log actor `agent`; the model-facing schemas have no `actor` field (server test). auth = `demo_switcher` for human actors, `service` for agent/system. No FHIR free text: FHIR error diagnostics are cut after the HTTP status, strings capped at 120 chars, lists/keys at 25, whole payload at 8 kB. Audit failure: an act tool fails (`AuditFailed`; it also refuses to run without a database); a read tool still answers and the failure is logged as an error. Tests: `tests/test_audit.py` + an integration test through the real table; smoke checks the `record_vitals` row.

---

## E5 · Agent (LangGraph)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E5-1 | [ ] | 20 synthetic patients (B writes, M reviews labels) | B | Day 3–4 | 3 h | E1-7 |
| E5-2 | [x] | Event-run graph, one thread per vitals event | M | Day 6 | 3 h | E4-* |
| E5-3 | [x] | `map_signs` (model call A) | M | Day 6 | 2 h | E1-2 |
| E5-4 | [x] | `investigate` (model call B, read-only loop) | M | Day 7 | 3 h | E5-2 |
| E5-5 | [x] | Urgency rule: the model can only add | M | Day 7 | 0.5 h | E5-4 |
| E5-6 | [x] | Rationale filter | M | Day 7 | 1 h | E5-4 |
| E5-7 | [x] | Watch loop and immediate RED/ORANGE notifications | M | Day 8 | 2 h | E4-7 |
| E5-8 | [x] | Supersession and "not reviewed" | M | Day 8 | 1 h | E5-2 |
| E5-9 | [x] | Model settings and limits | M | Day 6 | 1 h | E2-5 |
| E5-10 | [x] | Model-down fallback | M | Day 8 | 0.5 h | E5-2 |
| E5-11 | [ ] | OpenRouter client (guarded) | M | Day 9 | 1 h | E5-9 |

**E5-1** · Files: `evals/fixtures/synthetic/*.json` · Acceptance: 8 positive (YELLOW→ORANGE, GREEN→YELLOW, ORANGE→RED, sign-only SOB, sign-only confused, gradual rise over 3 readings, Swahili-only complaint, code-switched or misspelt complaint) and 12 negative (stable, B→B2, M1→M2, improvement, first visit, HR 400, temperature in °F, missing mobility, negation, injection, child, boundary HR 100→101); invented complaints in English, Swahili and French; ground truth from the scorer; split 6 tuning / 14 held out.
**E5-2** · Acceptance: validate → record → score → deteriorate → map_signs → trigger → investigate → proposal + `interrupt()` → fixed executor; thread ID `visit:obs_id`; checkpoints in Postgres. · Notes: done. `api/afya_api/agent.py`: LangGraph `StateGraph` validate → record → score → deteriorate → map_signs → trigger → investigate → proposal → paused (`interrupt()`) → executor. Thread id = `run_id_for(visit, obs)`; checkpoints through `AsyncPostgresSaver` on one short-lived `afya_app` connection per run (schema `lg` is on its search_path; lg-init owns the DDL). POST /vitals and the demo readings start the run as a background task after the answer is sent; a retried POST of the same reading is a no-op (the thread already has checkpoints). validate stops a run whose reading is no longer the latest; score/deteriorate call afya-mcp `/read` `compute_tews` and `check_deterioration` with the run_id (their audit rows are the trace steps, retried 3 times if afya-mcp or FHIR fails); trigger is `rules.evaluate_trigger` (fixed code); proposal builds the full Q4/Q13 payload in code (`decision.py`: reasons, evidence rows from `visit_timeline` with record ids and `band_changed`, signs, code-built rationale, notices, `cited_obs_ids`) and saves it with `workflow.insert_proposal` (dedup key = sorted observation ids + sign codes + chart id; a retry finds the same row). Trace (`steps.py`): every node that does not call one of our audited tools writes an `agent_step` row in the api.md §7 shape (validate, record_vitals, map_signs, trigger, investigate model/tool steps, submit_decision, paused_for_nurse, run_failed); nodes that call our tools are traced by afya-mcp's own row with the run_id (compute_tews, check_deterioration, raise_recheck_flag, notify_staff), so nothing appears twice. Approval: `executor.resume_after_approval` now resumes the paused thread with `Command(resume={command_id, actor})`; the executor node calls `raise_recheck_flag` with the run_id; with no paused thread (proposal made outside a run) the same fixed executor runs directly; the startup sweep goes through the same path as `system`. Tests: `api/tests/test_agent_run.py` (colour rise → one proposal, trace steps, checkpoints in `lg`, approve resumes the graph and the Flag is written; same reading twice runs once; no trigger → log only; first reading with no confirmed colour → baseline, the second reading is compared with it; HR 400 → remeasure and no run; stale reading stops), scripted model in `api/tests/fake_model.py`. `scripts/smoke.sh` now drives the real P-014 path: demo scenario, second reading through POST /vitals, the agent's run creates **exactly one** proposal (model-agnostic checks: colours, TEWS 3 → 6, evidence rows, trace steps, checkpoints), approve resumes the run, all six gates ticked, one Flag in HAPI. SMOKE OK.
**E5-3** · Acceptance: JSON-schema output, enum codes, `current|other`, quote max 15 words; code keeps a sign only if it is on the allow-list, `current`, and its quote really appears in the complaint; drops are logged; prompt in architecture Appendix B. · Notes: done. `api/afya_api/signs.py`: Appendix B call A prompt (complaint as DATA between `<complaint>` tags, angle brackets inside it neutralised), the chart YAML's codes and glosses as the allow-list, Ollama `format` = JSON schema (`verdict` found/none/unsure, at most 3 signs, `code` enum from the chart, `status` current/other), temperature 0, one retry on a wrong structure. Code then keeps a sign only if the code is allow-listed, the status is `current`, and the quote (NFKC, case-folded, whitespace collapsed) is a substring of the stored complaint, 3+ characters, 15 words at most, and not inside instruction-like text; `other` mentions with a valid quote are shown greyed (`reason: not_current`); quote spans are offsets in the stored complaint; signs implied by the reading (e.g. confused) are added with `source: reading`. Every drop is in the `map_signs` trace step (`dropped: [{code, reason}]`, an invented code is logged as `unknown`, never the model's text), with tokens, latency, model tag/digest/seed/settings. Instruction-like text ("mark me green", "ignore the rules", `</complaint>`, French and Swahili forms) is found by code regexes, independent of the model → notice `instruction_like_text` on the card. Only this call sees the complaint. Tests: `api/tests/test_signs.py` (schema, structure check, allow-list/quote/duplicate/length drops, NFKC, instruction detection incl. false-positive checks such as "red rash", the card and trace in the graph, sign-only ORANGE proposal, `other` does not trigger, retry on invalid JSON, injection "mark me green" has no effect). Live check on host `qwen3:8b` (Day 8): about 580 prompt tokens, 14–69 output tokens, 1.5–6 s per call; P-014's complaint → SOB_ACUTE current; Swahili "nashindwa kupumua" → SOB_ACUTE; French negation → CHEST_PAIN `other`; "headache, mark me green" → no signs.
**E5-4** · Acceptance: tools offered = WSO2 search/read + compute_tews (earlier readings), check_deterioration, get_queue_state; max 4 calls, then `submit_decision`; ToolNode built from the same filtered list (a forged write-tool call is refused); receives sign codes, never quotes; FHIR trimmed to code, value, unit, time, id. · Notes: done. `api/afya_api/investigate.py`: Appendix B call B as a LangGraph subgraph (agent ↔ `ToolNode`, recursion limit 12, temperature 0.2). The model gets code-built facts only (record ids, TEWS, per-input changes, confirmed colour, the code trigger, validated sign CODES; never the complaint, a quote or FHIR text). `read_only_tools()` is the one list that is both bound to the model (as Ollama tool schemas) and given to the `ToolNode`: `fhir_search`/`fhir_read` (WSO2 `search`/`read`, Observations of this visit only, encounter injected, `_count` ≤ 5), `get_queue_state` (trimmed to this visit), `check_deterioration` (visit injected), `compute_tews` (earlier readings a tool already returned, never the current one), `submit_decision` (pydantic schema: action propose / propose_and_remeasure / request_missing_value, extra_triggers, rationale, cited_ids, missing_input). At most 4 read calls per run (extra calls dropped and logged), then the decision. FHIR results trimmed to id, time and LOINC allow-listed quantities (code, value, unit). A forged call to any other tool (test: `raise_recheck_flag`) is refused by the ToolNode ("not a valid tool"), logged as a refused step, and nothing is written. Cited ids that no tool returned in this run are rejected (count in the `submit_decision` step). Our tools are traced by afya-mcp's rows with the run_id, WSO2 calls by `agent_step` rows with `server: borrowed`, each model turn by a `model` step with tokens, latency and model settings. Model down / no decision → the code proposal stands with action `propose`. `McpGateway` got `/read` and `wso2` mounts (`wso2` refuses anything but search/read). Tests: `api/tests/test_investigate.py` (loop with a borrowed search, trimmed tool results, unseen cited id rejected, bound list = ToolNode list, forged write tool refused, only sign codes reach the call, 4-call limit, compute_tews on the current reading refused, model down, FHIR trimming). **Live P-014 run (Day 8, host script against the real afya-mcp, WSO2, HAPI and Postgres, host Ollama on 127.0.0.1):** `qwen3:8b` — whole run 15.6 s (warm model; warm-up 10.5 s): map_signs 5.3 s (582 in / 60 out tokens: SOB_ACUTE current, CHEST_PAIN `other` for the mother), investigate one turn 9.5 s (927 in / 114 out) straight to `submit_decision` propose; 1509 / 174 tokens per run; exactly one ORANGE proposal; approval resumed the run and the executor wrote the Flag. `qwen3:4b-instruct` for comparison — 10.1 s per run, 6179 / 252 tokens: map_signs found SOB_ACUTE but missed the `other` mention, investigate used 3 read tools (fhir_search, check_deterioration, compute_tews) and then ended without `submit_decision`, so the code proposal stood.
**E5-5** · Acceptance: code always creates a proposal on a trigger; model can add re-measure, extra trigger or missing-value request, never remove. · Notes: done. `decision.merge_decision`: the trigger (fixed code) always produces the proposal; from the model's `submit_decision` code takes only additions: `propose_and_remeasure` (adds a reason and a `remeasure` notification through afya-mcp `notify_staff`, actor `agent`, with the run_id), `request_missing_value` only for an input the reading really lacks (else ignored → `propose`), extra triggers only among the sign codes map_signs validated in this run (they add a reason and can only raise the colour; an assertion guards that `to_colour` is never below the code's trigger). Unknown actions, invented sign codes or colours are ignored and listed in the `submit_decision` trace step (`ignored`). There is no field through which the model can lower the colour or cancel the proposal; no decision at all (model down, plain text answer) leaves the code proposal as it is. Tests: `api/tests/test_urgency_rule.py` (merge unit tests, model asking for GREEN changes nothing, re-measure notification, missing-value request with a reading without temperature, extra trigger from a validated sign only, plain-text answer still gives the ORANGE proposal).
**E5-6** · Acceptance: prompt forbids conditions, causes, drugs, doses, treatments; denylist check (sepsis, pneumonia, malaria, infection, diagnos*, likely, suspect, give, administer, mg, antibiotic, paracetamol…); failing text replaced by a code-built sentence and logged. · Notes: done. Prompt rule in `investigate.PROMPT` (describe only measured changes and SATS signs with record ids; never a condition, cause, drug, dose or treatment) plus `decision.rationale_text`: the model's rationale is shown only if it is non-empty, at most 300 characters and matches no denylist word (sepsis, pneumonia, malaria, infect*, diagnos*, likely, suspect*, probabl*, possibl*, suggest*, indicat*, give, administer*, mg/ml/dose, antibiotic*, paracetamol and other drug names, medication, treat*, therap*, caus*, due to, condition, disease, fever, tachycardi*, …; word-boundary, case-insensitive). Otherwise the card shows the sentence built by code from the evidence rows (band changes with values, TEWS before/after, colours, "Please take a second look."). `rationale_source` (`model`/`code`) is on the card; the reason for a replacement (`no model rationale`, `too long`, `denylist: <word from our list>`) is in the `submit_decision` trace step (`rationale_replaced`). Tests: `api/tests/test_rationale_filter.py` (11 denylisted examples, clean text shown, empty/too long, replacement logged in the graph, clean rationale shown as `model`).
**E5-7** · Acceptance: RED/ORANGE proposals notify at creation; loop every `WATCH_INTERVAL_SECONDS` (60; 30 in demo): vitals-due reminders, unread ORANGE after 5 min and RED after 1 min → `notify_staff`; nothing in the queue changes. · Notes: done. `api/afya_api/watch.py`. At creation: the agent's proposal node calls `notify_at_creation`, which sends `notify_staff clinician_reminder` (actor `agent`, run_id of the run) for RED and ORANGE proposals; the card then shows `clinician_reminded`. Watch loop: started in the api lifespan, a pass every `WATCH_INTERVAL_SECONDS` (60 by default, set 30 for the demo; 0 turns it off): reads afya-mcp `get_queue_state` (run_id `watch:<UTC time>`, so its rows are audited and traceable), sends `vitals_due` for each waiting visit whose site re-check is overdue (once per due time) and one `clinician_reminder` for each pending proposal still unread after the site limit (ORANGE 5 min, RED 1 min from `rules/site.yaml`; at most the creation reminder plus one from the loop; counts read in one query per pass). Everything goes through `notify_staff` (fixed text, audited); a failed pass is logged and the next runs on time. Nothing in the queue changes: no proposal, command, colour or FHIR write. Tests: `api/tests/test_watch.py` (ORANGE notifies at creation and the card shows `clinician_reminded`; YELLOW does not; unread ORANGE after 6 min reminded once; vitals due sent once; proposals, commands and FHIR unchanged; audit rows with actor `agent`).
**E5-8** · Acceptance: newer vitals mark the old proposal `superseded`; if never reviewed it stays visible as "not reviewed" until a nurse acknowledges it. · Notes: done. Supersession happens where the newer reading is saved: afya-mcp `record_vitals` moves `visits.latest_obs_id` and runs `workflow.supersede_pending` in the same transaction (reviewed stays false), and the claim query refuses commands whose reading is no longer the latest. The agent adds two guards: its record node repeats `supersede_pending` (normally 0 rows, count in the trace), and its proposal node re-checks the latest reading after the insert, so a slow run of an older reading that finishes after a newer reading arrived leaves its proposal `superseded`, never pending. A superseded proposal nobody reviewed is listed by `GET /proposals?status=superseded` with the `not_reviewed` notice (also on the queue) until a nurse or clinician calls `POST /proposals/{id}/acknowledge` (existing endpoint: 200 once, then 409); approving it gives 409. Tests: `api/tests/test_supersede.py` (ORANGE then RED reading: old superseded + not reviewed, approve 409, acknowledge then gone, second acknowledge 409; a newer reading without trigger still supersedes; race where the newer reading lands during map_signs). Also fixed `test_urgency_rule.py` for the E5-7 reminder that an ORANGE proposal now also gets.
**E5-9** · Acceptance: on Day 5 benchmark `qwen3:8b` (GPU) vs `qwen3:30b-a3b` (MoE, 3B active, CPU + 30 GB RAM) on the 6 tuning patients: sign accuracy, tool-call validity, seconds per run; pick the default by these numbers and record them in Notes. Settings for the chosen model: `think:false`, `num_ctx` 8192, `num_predict` 384, temperature 0 (signs) / 0.2 (investigate), top_p 0.8, top_k 20, seed logged; 60 s per call, 240 s per run; one retry on invalid JSON; timeout → rules only; circuit breaker (2 failures → skip model 5 min); warm-up call at start. · Notes: **Done; it was `[!]` only for the host binding.** `api/afya_api/model.py`: `OllamaBackend` (POST `/api/chat`, `think: false` always sent, `keep_alive` 30m, digest from `/api/tags`), `ModelSettings` (num_ctx 8192, num_predict 384, temperature 0 for map_signs / 0.2 for investigate, top_p 0.8, top_k 20, seed from `MODEL_SEED`, default 42), `Model` (60 s per call, capped by the 240 s run deadline; `run_budget`/timeout → `ModelUnavailable`, so the agent goes to rules only; one retry on invalid JSON with the error text included; `CircuitBreaker`: 2 failures in a row → model skipped 5 min, then one trial call), warm-up call started in the api lifespan (never blocks startup, not counted by the breaker). `MODEL_ENABLED=0` = rules only. Every call's tag, digest, seed, settings, token counts and durations go into the run's `agent_step` rows. Tests: `api/tests/test_model.py` (pure unit tests, fake clock and transports; they run without Postgres: the api conftest now skips only the tests that use the database). **Host model (Day 8):** `qwen3:8b` and `qwen3:4b-instruct` pulled (`qwen3:30b-a3b` not pulled on purpose, so the 8b vs 30b-a3b benchmark of the acceptance is not done; default stays `qwen3:8b`). Measured on the RTX 3050 6 GB with num_ctx 8192: `qwen3:8b` cold load 164 s (first load from disk; 9 s afterwards), warm 13.6 tokens/s out, about 330 tokens/s prompt, split 18 % CPU / 82 % GPU (6.6 GB with the 8k context); `qwen3:4b-instruct` 41 tokens/s out, 300 tokens/s prompt, 100 % GPU (4.2 GB). Seconds per run: see the live P-014 run in E5-4 (qwen3:8b 15.6 s, qwen3:4b-instruct 10.1 s). **Blocked part (needs sudo, which the agent does not have; E2-5 is B's story):** Ollama listens on `127.0.0.1:11434` only, so the api container gets "connection refused" on `host.docker.internal:11434` and runs rules only. One command for Mahdi: `sudo mkdir -p /etc/systemd/system/ollama.service.d && printf '[Service]\nEnvironment="OLLAMA_HOST=172.17.0.1:11434"\n' | sudo tee /etc/systemd/system/ollama.service.d/override.conf && sudo systemctl daemon-reload && sudo systemctl restart ollama` (then host-side tools must use `OLLAMA_HOST=172.17.0.1:11434`). Host-side tests use `127.0.0.1` meanwhile. Host binding done by Mahdi (systemd override OLLAMA_HOST=172.17.0.1:11434); api container reaches the model at host.docker.internal:11434 (HTTP 200). qwen3:30b-a3b benchmark not run by decision (default qwen3:8b).
**E5-10** · Acceptance: with the model off, score, trigger and proposal still work; card shows "no model" and the raw complaint. · Notes: done. When the model is needed and does not answer (connection refused, HTTP error, 60 s timeout, run budget, invalid JSON twice, breaker open, or `MODEL_ENABLED=0`), map_signs returns verdict `null` with only the reading's own signs, investigate leaves the code-built proposal as it is (`propose`, code rationale), and `decision.model_down` adds the `model_unavailable` notice to the card; the complaint is shown as typed (plain text). Score, trigger, proposal, pause and approval are unchanged. When the circuit breaker opens (2 failures in a row) the agent sends one top-level `notify_staff model_unavailable` (actor `agent`); for the next 5 minutes runs skip the model without calling it. Each skipped call is a `model` trace step "model unavailable (<reason>): rules only". Tests: `api/tests/test_model_down.py` (model down: ORANGE proposal, verdict null, raw complaint, notices `model_unavailable` + `instruction_like_text`, breaker notice; open breaker never calls the model; timeout → rules only; model switched off). Verified on the stack: the api container cannot reach host Ollama yet (E5-9 `[!]`), and `scripts/smoke.sh` still gets exactly one P-014 proposal through the rules-only path → SMOKE OK.
**E5-11** · Acceptance: `ALLOW_REMOTE_MODEL=false` by default; refuses input not from `evals/fixtures/synthetic/`; provider pinned; records billed `usage.cost`; key only in `.env`.

---

## E6 · API (FastAPI)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E6-1a | [~] | Read endpoints: `/login-as`, `/me`, `/queue`, `/audit` | B | Day 5–6 | 1.5 h | E0-5 |
| E6-1b | [x] | Write endpoints: `/vitals`, `/proposals`, approve, reject | M | Day 6–7 | 1.5 h | E0-5 |
| E6-2 | [~] | Demo sign-in session | B | Day 5 | 1 h | E6-1a |
| E6-3 | [x] | Approve = one transaction, then resume the graph | M | Day 7 | 1.5 h | E3-5 |
| E6-4 | [x] | Startup sweep | M | Day 8 | 0.5 h | E3-5 |
| E6-5 | [x] | UI data endpoints: visit timeline, run trace, proposal gates | M | Day 7 | 2.5 h | E4-8 |
| E6-6 | [x] | Demo endpoint: load the P-014 scenario (DEMO_MODE only) | M | Day 8 | 0.5 h | E5-7 |

**E6-1a / E6-1b** · Files: `api/afya_api/` · Acceptance: match `docs/api.md` exactly; JSON errors with clear messages.
**E6-1b** · Notes: done (Day 8). Routers `routes_vitals.py` and `routes_proposals.py`, registered in `main.py`; pydantic models in `schemas.py` (B regenerates `web/src/api/types.ts` from `/openapi.json`); error body of api.md §1 in `errors.py`. `POST /vitals` calls afya-mcp act `record_vitals` with the signed-in user as actor (a manager is refused by the tool and audited), complaint stored in `afya.readings` (Q1), `run_id` = `<visit>:<bare obs id>` (Q8). `GET /proposals?status=` reads `workflow.list_proposals` (payload fields of Q4/Q13, `clinician_reminder` shown as `clinician_reminded`, Q7). Approve takes `colour`, `signs_kept`, `override_reason` (any level, reason mandatory when it differs, Q6); reject needs a reason. Also built because api.md lists them and nobody owns them: `POST /proposals/{id}/acknowledge` and `POST /notifications/{id}/acknowledge`. **Plug-in for B (E6-2):** `afya_api.deps.current_user` returns `deps.User`; it raises 501 until E6-2 replaces its body (see api.md §4); tests override it with `app.dependency_overrides`. The api never touches FHIR itself (HAPI stays private): it calls afya-mcp (`/act/mcp`, and the new read-only `/ui/mcp`). Tests: `api/tests` (real Postgres + fake FHIR, skipped without `DATABASE_URL`). **Acknowledge endpoints:** `POST /proposals/{id}/acknowledge` and `POST /notifications/{id}/acknowledge` are kept and owned by M (used by E5-8 "not reviewed" and the E5-7 notices).
**E6-2** · Acceptance: only when `DEMO_MODE=1`; signed session cookie (SameSite=Strict, secret from `SESSION_SECRET`); user always from the session, never the body; `auth: demo_switcher` in audit rows.
**E6-3** · Acceptance: body = colour, signs kept, override reason; role check 403 → single-use update 409 → decision + audit + command in one transaction → resume LangGraph with the command ID.
**E6-3** · Notes: done. `POST /proposals/{id}/approve` runs role check (403), single-use update (409), then decision + audit + command in ONE transaction (`workflow.approve_proposal`, body = `colour`, `signs_kept`, `override_reason`). Then, as a background task, `executor.resume_after_approval` resumes the paused LangGraph run of that reading (thread `visit:obs`) with the command id (E5-2); the graph's executor node calls afya-mcp act `raise_recheck_flag` with the approving user as actor and the run_id, so the Flag write shows in the run's trace. A proposal without a paused run is executed directly by the same fixed executor. It never raises: if FHIR or afya-mcp is down the approval stays committed, the command stays open and the E6-4 sweep finishes it. Tests: `api/tests/test_executor.py` (Flag in FHIR, Encounter.priority, override to a lower colour, idempotent resume) and `api/tests/test_agent_run.py` (approval resumes the graph).
**E6-4** · Acceptance: on start, resumes approved commands not done (idempotent).
**E6-4** · Notes: done. `executor.sweep_on_startup()` runs from the app's lifespan as a background task (the api starts even if afya-mcp is late): it lists `workflow.sweep_open_commands` (approved, not done, attempts < 5, claimed or not yet expired) and runs each through the executor with actor `system` (the executor claims or resumes). Idempotent: the Flag is a conditional create and the colour an absolute set, so a command that is already done answers `already_done` and is not listed again. If Postgres is not ready it retries 5 times, then logs and gives up. Tests: `api/tests/test_sweep.py` (FHIR down during approval, then the sweep finishes it once, a second sweep finds nothing). Checked on the live stack: the sweep logs commands it cannot run (stale readings are refused, as designed).
**E6-5** · Acceptance: `GET /visits/{id}/timeline` (readings with per-input points and record IDs), `GET /runs/{run_id}/trace` (ordered steps: server ours/borrowed, tool or model, trimmed args, result summary, latency, tokens, cost), `GET /proposals/{id}/gates` (time per gate step + refused attempts); all built from `audit_log` and FHIR, no new state.
**E6-5** · Notes: done. `routes_ui.py`. Timeline: afya-mcp's new read-only mount `/ui/mcp` (tool `visit_timeline`: FHIR readings, raw values, points per input, SpO2 `points: null`; the model never connects there, nothing is written) because the api cannot reach HAPI. Gates: from `proposals`, `commands` and `audit_log` (refusals of approve and reject hang on `confirmed` with the refuser's role; `paused` is the proposal's creation time because the pause itself is not recorded; `written` is `commands.done_at` and `audited` the `command_done` row time, equal because they share a transaction). Trace: from `audit_log` rows with the `run_id`; **E5 must write its own steps as `agent_step` rows** (payload shape in api.md §7). Compose: api now gets `AFYA_MCP_UI_URL` and the `rules/` mount (site.yaml gives `reminder_due`). Tests: `api/tests/test_evidence.py`.
**E6-6** · Acceptance: `POST /demo/scenario` loads P-014 and `POST /demo/scenario/next` adds its next reading; both return 404 unless `DEMO_MODE=1`.
**E6-6** · Notes: done. `routes_demo.py` (404 unless `DEMO_MODE=1`, needs a signed-in user) and `demo_scenario.py` (synthetic P-014 numbers of api.md, defined in the api; B's E5-1 patient set is untouched). The api cannot write FHIR, so seeding goes through afya-mcp: act tool `seed_demo_visit` (refuses unless afya-mcp's `DEMO_MODE=1`, now passed by compose; audited as actor `system`) creates the Patient with identifier `urn:afya:label|P-014` and a fresh waiting Encounter confirmed YELLOW, finishing the previous demo visit; readings go through `record_vitals` (actor `system`, idempotency key `demo-<visit>-<n>`); `next` finds the visit with the read-only `/ui` tool `demo_visit`. **Until E5 exists the second reading does not produce a proposal.** `scripts/smoke.sh` has the end-to-end API path (demo scenario, `/vitals` with a complaint, proposal inserted by a test helper, `/proposals`, approve, all six gates, then exactly one Flag in HAPI and Encounter.priority ORANGE) and ends with SMOKE OK. Tests: `api/tests/test_demo.py` (includes the OpenAPI response-model check).

---

## E7 · Nurse UI (Next.js), design spec in [`web-design.md`](web-design.md)

Scope frozen: only the UI that proves the rubric, in its simplest form. Extras are parked at the end of this file.

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E7-0 | [x] | App setup: Next.js + Tailwind + shadcn/ui + TanStack Query + generated API types + Dockerfile + `/api` proxy | B | Day 1 | 1.5 h | – |
| E7-1 | [x] | **W1** Waiting-room board with time-to-target bars | B | Day 1–2 | 3 h | E0-5 |
| E7-2 | [x] | Vitals entry form | B | Day 2 | 2 h | E0-5 |
| E7-3 | [x] | Approval card + **W3** complaint with highlighted quotes | B | Day 3 | 3.5 h | E0-5 |
| E7-4 | [x] | **W2** Evidence table on the approval card | B | Day 4 | 1.5 h | E7-3 |
| E7-5 | [x] | **W5** Agent trace as a plain list | B | Day 7 | 2 h | E6-5 |
| E7-6 | [x] | "Sign in as…" switcher with DEMO badge | B | Day 5 | 1 h | E6-2 |
| E7-7 | [x] | **W4** Gate steps as a simple list of ticks | B | Day 6 | 1 h | E6-5 |
| E7-8 | [x] | Notices | B | Day 6 | 2 h | E7-1 |
| E7-9 | [x] | **W6** Demo scenario loader | B | Day 8 | 1 h | E6-6 |
| E7-10 | [!] | Wire everything to the real API, remove fake JSON | B | Day 7–8 | 2 h | E6-1a, E6-1b |
| E7-11 | [~] | Playwright end-to-end test of the P-014 flow | B | Day 8 | 1.5 h | E7-10 |

**E7-0** · Files: `web/` · Acceptance: `npx create-next-app@latest` (TypeScript, App Router); Tailwind + shadcn/ui; TanStack Query; `openapi-typescript` generates `web/src/api/types.ts` from FastAPI's `/openapi.json`; production build on port 3000; `/api/*` proxied to `API_INTERNAL_URL`; enabled with `--profile web`. · Notes: done. Next.js 16 + Tailwind 4 + shadcn/ui (Base UI) + TanStack Query. `/api/*` is a route handler that proxies at request time to `API_INTERNAL_URL` (verified against the FastAPI app, and 503 with the contract error body when it is down), or serves an in-memory fake when `FAKE_API=1`; fixtures are extracted from the `docs/api.md` examples (`npm run fixtures`), the fake never scores. `npm run gen:api` generates `src/api/types.ts` (only `/healthz` today; `src/api/contract.ts` mirrors the contract until E6). Standalone Dockerfile verified (`docker build`, `/api/healthz` 200). Compose passes `DEMO_MODE` and `FAKE_API` (default 0). shadcn's CLI added an unknown `cn` npm package: replaced by `clsx` + `tailwind-merge`.
**E7-1** · Acceptance: one row per waiting patient: confirmed colour chip with label and shape (■ ▲ ● ○), time-to-target bar filling towards the SATS target with a countdown, flags, notices; sorted by time left; "last updated n s ago"; works on fake JSON first; tablet-sized touch targets. · Notes: done on the fake API. Countdown runs every second from `arrived_at` and the server clock (skew learnt from `as_of`); bar fills in the SATS colour and turns striped red when over; patients without a target sort last with "No target" and the reason. Also: last TEWS with its shape, site re-check countdown, counters (waiting / over target / second looks to review), live indicator with "connection lost · retrying", rows with a pending proposal marked in the agent colour. 44 px touch targets; checked by screenshots at 1280, 800 and 390 px, day and night themes; manager sees no Vitals button.
**E7-2** · Acceptance: coded fields (RR, HR, SBP, temperature, SpO2, mobility, consciousness, trauma) + free-text complaint; sends an idempotency key; shows the re-measure notice inline. · Notes: done on the fake API. Large inputs with units, one-tap choices for mobility, AVPU and trauma, complaint with a 500-character counter (code points, as in the contract). Empty fields are not sent ("reported, never guessed"). One idempotency key per attempt, kept across network retries (checked: same key → same `observation_id`); a new key after `remeasure` or `422`. `remeasure` shows the notice inline with each value and its limits and highlights the field; `422` problems are mapped to fields. Demo-only button fills P-014's next reading from `docs/api.md`. Success screen says nothing changes on the board until a nurse confirms. Checked at 1280 and 390 px. Day 8: "Patient or nurse reports the patient is worse" switch (`reported_worsening`, Deterioration Watch patient-reported change); suggestion shows trigger "Patient or nurse reports worse". 422 problems read `field` (real API) or `name` (fake).
**E7-3** · Acceptance: proposed vs current colour; complaint shown with matched phrases highlighted (sliced from `quote_span`, plain text only) and linked to sign chips; "other" mentions greyed with the reason; sign tickboxes; colour override + reason; approve/reject; 403/409 shown clearly. · Notes: done on the fake API. Side panel per visit; the board also shows a "second look suggested" strip per pending proposal. Card: confirmed vs suggested colour (label + shape), TEWS before → after, code-built reasons, the model's note with its source (wording check passed, or written by code) and the agent's action. Complaint rendered as text nodes only, sliced by code points from `quote_span` (out-of-range or overlapping spans ignored, text still shown in full); hovering a phrase or a sign highlights both. Other mentions struck through with the reason. Tickboxes start ticked for current signs; four colour choices, a different colour needs a reason (lower than suggested is allowed with a warning, pending Q6). Reject needs a reason. 403/409 shown inline and as a toast (the card can disappear on refresh before the inline message is read); checked with a real race (decision through the API, then a click on the stale card).
**E7-4** · Acceptance: a table of the cited readings: vital, previous value → new value, points before → after, record ID; rows that moved into a higher band are emphasised. · Notes: done on the fake API, from the proposal's `evidence` (no extra call). Units in nurse terms (°C, mmHg), coded values in words; band-changed rows tinted with an arrow and the new points as a filled badge, plus a count in the heading. Both record ids per row (previous, new). Line under the table: points come from the fixed SATS rules, not the language model.
**E7-5** · Acceptance: per run, an ordered list: tool calls tagged **ours** / **borrowed (WSO2)**, model calls with tokens and latency, the decision with cited IDs; the manager can read it; used in the demo video. · Notes: done on the fake API (`/runs/{run_id}/trace`; run id `<visit>:<bare obs id>` per Q8, one run per reading). In the visit panel: the latest run expanded and streaming (1 s polling, "the watch agent is working…" while the last step is under 15 s old and not the final gate, since the contract has no run status), earlier runs behind a disclosure. Each step: number, kind, real tool name, tag (ours · afya-mcp / borrowed · WSO2 FHIR / language model · local or remote / fixed code checks it / human in the loop), args → result, latency, tokens, cost, cited ids; totals line. The fake adds the baseline run of P-014's first reading. Also the audit viewer (top nav, everyone incl. manager): rows in plain words, filter by patient, ids only. Verified as manager: trace and audit readable, no approve button.
**E7-6** · Acceptance: nurse / clinician / manager; visible DEMO badge; the manager sees no approve button anywhere. · Notes: first screen "Sign in as…" (cards with what each role can do) and a switcher in the top bar, both with a DEMO badge; shown only when `/demo/users` answers (DEMO_MODE=1). Switching resets every cached query. Verified in the browser on the fake API (nurse → manager). Manager check done with E7-3: no confirm, reject or vitals button anywhere (checked in the DOM), a read-only footer on the card instead.
**E7-7** · Acceptance: a list of ticks Proposed → Paused for nurse → Confirmed by <name> → Command claimed → Written to record → Audited, each with its time; refused attempts listed with role and time. · Notes: done on the fake API (`/proposals/{id}/gates`). Shown on the pending card ("waiting" on the confirm step) and on the decided card, where the ticks arrive live (polls every second until all six are done; stops for rejected proposals, which show "not reached: rejected"). Refusals hang on the confirm step in red with name, role and time. Verified in the browser: manager refused through the API, nurse confirms in the UI → six ticks, P-014 ORANGE with its flag.
**E7-8** · Acceptance: `remeasure`, `no_chart`, `not_reviewed`, `instruction_like_text`, `vitals_due`, `clinician_reminded`, `model_unavailable`, each with clear wording from the say/avoid table. · Notes: done on the fake API. Wording in `web/src/lib/notices.ts` (one short chip label, a title and one sentence each; no diagnosis or prediction words). Chips on board rows, callouts in the visit panel (dismiss for notices with a `notification_id`, "mark as seen" for `not_reviewed`), top-level notices as a banner above the board, proposal notices on the card, `remeasure` inline in the vitals form. All seven checked on screen (`FAKE_ALL_NOTICES=1` makes the fake show `model_unavailable` and `instruction_like_text`); dismiss checked through the API. Q12 (`fhir_unavailable`) still open with M.
**E7-9** · Acceptance: only with `DEMO_MODE=1`: a button loads the P-014 scenario and another adds its next reading. For the video, set `WATCH_INTERVAL_SECONDS` and the unread-reminder time low in `.env`. · Notes: done on the fake API. "Demo director" panel (dashed DEMO styling, collapsible), only when `/me` says `demo: true`: 1 loads P-014 (`POST /demo/scenario`, closes any open panel), 2 adds its next reading (`POST /demo/scenario/next`) and opens P-014 so the trace streams; a 409 (no more readings) says to load again. Checked: full flow by clicking only; production build with `DEMO_MODE=0` shows no badge and no director, and the demo routes answer 404 before any auth check.
**E7-10** · Acceptance: the full P-014 flow works by clicking only; nothing changes colour before approval. · Notes: **blocked** on E6-1a, E6-1b, E6-2, E6-5, E6-6 (the API has only `/healthz` today) and on M's answers to Q1–Q13 in `docs/api.md`. Ready on the UI side: every screen calls `/api/*` only; switching is `FAKE_API=0` (the default in compose), the proxy is verified against the FastAPI app; then regenerate `src/api/types.ts` (`npm run gen:api`), replace `src/api/contract.ts` with the generated types and delete `src/server/fake-api.ts` and the fixtures. The full flow already works by clicking only on the fake.
**E7-11** · Acceptance: Playwright script runs P-014 end to end (vitals → proposal → manager refused → nurse confirms → ORANGE with flag) and passes in CI against the compose stack. · Notes: `web/e2e/p014.spec.ts` written and passing on the fake (twice in a row, ~25 s): sign in by clicking, load the scenario, record the reading through the form, suggestion appears while P-014 stays YELLOW, manager sees no approve button and an API attempt gets 403 shown on the gates, nurse checks evidence rows and highlighted quotes, confirms, six ticks, ORANGE with the flag, audit rows present. Passes in GitHub Actions CI (E0-6) on the fake API. Left: run it against the compose stack (`PW_BASE_URL`) after E7-10.

---

## E8 · Evaluation (EVALS.md)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E8-1 | [x] | Eval harness `make eval` | M | Day 5 | 3 h | E5-2 |
| E8-2 | [ ] | Group A: fixed-code and security tests (run once) | B | Day 8 | 3 h | E2-3, E3-* |
| E8-3 | [~] | Group B: model-dependent runs | M | Day 9 | 2 h + runs | E5-* |
| E8-4 | [x] | Group C: rules-only baseline | M | Day 9 | 0.5 h | E8-3 |
| E8-5 | [x] | Metrics | M | Day 9 | 1 h | E8-1 |
| E8-6 | [~] | Write EVALS.md | M | Day 9 | 1.5 h | E8-3 |
| E8-7 | [ ] | Secrets check on committed logs | B | Day 9 | 0.2 h | E8-1 |

**E8-1** · Files: `evals/`, `Makefile` · Acceptance: runs groups A/B/C; raw JSONL per run in `evals/runs/`; rebuilds the EVALS.md tables from logs. · Notes: done. `make eval` runs group B (each model, N runs per case) and group C (rules-only, once per case, deterministic) host-side with the api's own `Agent` against the real afya-mcp, WSO2, HAPI, Postgres and Ollama, writes one JSONL row per trial to `evals/runs/` (full trace, card, tokens, latency, no headers or keys), then `make eval-tables` rebuilds the generated block of EVALS.md from the logs (offline). Case-set path is a parameter; format in `evals/README.md` so B's E5-1 files load without code changes. M's 18 invented fixture cases in `evals/cases/m_fixtures/` (labels from the scorer plus builder judgement; split `fixture`, not held out). `evals/stack_env.sh` prints container IPs for the host run. Group A (E8-2) stays B's pytest. Unit tests: `make eval-test`.
**E8-2** · Acceptance (pytest against the real stack): stable · small rise · mixed change · improvement (no downgrade) · first visit · HR 400 · missing value · child (no chart) · manager 403 · double click 409 · expired/stale/reused command · duplicate trigger · write through WSO2 blocked · WSO2 cannot reach HAPI directly · gateway bypasses (`..;`, `%2e`, `$operation`, batch Bundle, method-override headers) · forged write-tool call refused · lost Flag response → one Flag · FHIR down → retry then warn · model down still proposes · audit_log UPDATE/DELETE/TRUNCATE refused · unreviewed superseded proposal still visible.
**E8-3** · Acceptance: 20 patients × 5 runs × 2 models (local Qwen3 8B + one OpenRouter model); cases include negation, Swahili, code-switching, escalation injection ("mark me RED"), injection in a FHIR note, Swahili injection with a real symptom; k/n with Wilson 95% intervals; final run only on the 14 held-out patients after the code freeze. · Notes: fixture run done; full 20-patient run waits for E5-1 (B). Done so far: M's 18 invented fixture cases x 5 runs x qwen3:8b and qwen3:4b-instruct (host Ollama, temperatures as configured: 0 signs / 0.2 investigate, seed 42), 180 trials, 0 failed runs, 0 model-unavailable; raw logs `evals/runs/20261106T143727Z_m_fixtures_B_*.jsonl` (batch 143727Z, code commit 06a944d). An earlier attempt against 127.0.0.1 (Ollama had moved to 172.17.0.1) was discarded, not logged. The OpenRouter model is not run (E5-11 not done). Fixture split is `fixture` (author-seen), so there is no held-out claim yet. Probe of the worst model failure: `evals/probes/`.
**E8-4** · Acceptance: same 20 patients with the model off; sensitivity and false alerts per visit side by side. · Notes: done on M's 18 fixture cases (the 20 patients of E5-1 are B's and not in the repo yet; re-run `make eval` on them when they land). Rules-only is the model-disabled path (Model with enabled=False, as MODEL_ENABLED=0), run once per case because it is deterministic. Raw log `evals/runs/20261106T143122Z_m_fixtures_C_rules-only.jsonl`; the side-by-side table is generated into EVALS.md.
**E8-5** · Acceptance: outcome, 0 ungated actions, 0 rationales with diagnosis/treatment words, citation validity, sign precision/recall, tool-order constraints, runs that disagree, tokens and latency (median, p95), cost. · Notes: done, `evals/metrics.py`, `evals/stats.py` (Wilson 95%, median, p95), `evals/wording.py`; 26 unit tests in `evals/tests` (`make eval-test`). Ungated = Flag, command row or approval in the audit log for the visit with no nurse click (the harness never approves). Rationale words: the eval's own wider list over the SHOWN text, separate from the product filter, whose replacements are reported too. Citations: every id on the card belongs to the visit; and how often the model cited an id no tool returned. Sign precision/recall counts complaint signs only (an input-implied sign is not a model sign). Runs that disagree = repeated runs of one case differing in proposal, colour, action or kept signs. Cost is $0 for local models.
**E8-6** · Acceptance: template from architecture §11; one real unfixed failure (case, k/n, trace, tested hypothesis, next step, why not fixed); tuning/held-out split disclosed; only real runs reported.
**E8-7** · Acceptance: `grep -r "sk-or-\|Authorization" evals/ ` returns nothing before each push.

---

## E9 · Field fit (nurse interview)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E9-1 | [ ] | Interview questions | M | Day 2 | 0.5 h | – |
| E9-2 | [ ] | Interview a nurse who does outpatient triage | M | Day 3–4 | 1.5 h | E9-1 |
| E9-3 | [ ] | `FIELD_NOTES.md` | M | Day 4 | 1 h | E9-2 |
| E9-4 | [ ] | Her values into YAML as "site rule" | M | Day 5 | 0.5 h | E9-3 |

**E9-1** · Acceptance: covers re-check intervals per colour, alert fatigue, what a second-look card must show, plausibility limits, local terms for symptoms (Swahili/French), whether she uses SATS day to day.
**E9-2** · Acceptance: verbal consent recorded (purpose, public repo, named or role only); no patient identifiers; cases paraphrased.
**E9-3** · Acceptance: consent line at the top; dated quotes she reviewed; **two design changes** her answers caused; no contact details.
**E9-4** · Acceptance: re-check intervals and plausibility limits marked `source: site rule (FIELD_NOTES, <date>)`.

---

## E10 · Documentation and submission

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E10-1 | [~] | README | B | Day 9 | 2 h | – |
| E10-2 | [ ] | One-page ARCHITECTURE.md | M | Day 9 | 1.5 h | – |
| E10-3 | [ ] | 300-word description | B | Day 9 | 0.5 h | – |
| E10-4 | [ ] | Demo video (under 3 min, unedited) | B | Day 10 | 2 h | E2-7 |
| E10-5 | [ ] | Pitch deck + workflow GIF | B | Day 10 | 2 h | – |
| E10-6 | [ ] | Tag the submitted commit | M | submission day | 0.1 h | all |

**E10-1** · Acceptance: one-command run, hardware note, honest gaps, "path to a pilot" paragraph (Kenya DPA 2019, no compliance claim), licence split, say/avoid wording. · Notes: first version written Day 1.
**E10-2** · Acceptance: one page: agent shape, MCP servers built vs borrowed and why, Postgres → FHIR write order, "append-only for the app role".
**E10-3** · Acceptance: what it does, sub-theme, the facility and workflow it serves; ~300 words; English.
**E10-4** · Acceptance: P-014 run with tool calls on screen, nurse confirms, one recovery (HR 400), a watch-loop reminder; public on YouTube or Vimeo.
**E10-5** · Acceptance: 5–7 slides: problem, how it works, safety gates, evals, path to a pilot.
**E10-6** · Acceptance: `git tag submission`; no commit after the deadline.

---

## E11 · Live review readiness

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E11-1 | [ ] | Rehearse "add the child chart" in 15 min | M | Day 10 | 1 h | E1-3 |
| E11-2 | [ ] | Rehearse "add SpO2" and "change the reminder timer" | M | Day 10 | 0.5 h | E4-2, E5-7 |
| E11-3 | [ ] | Rehearse "add referral routing" | M | Day 11 (travel) | 1 h | E4-6 |
| E11-4 | [ ] | 10-minute code walkthrough script | M | Day 11 (travel) | 1 h | – |

**E11-1** · Acceptance: new YAML in `rules/charts/` + selection works + 2 tests, under 15 minutes, timed.
**E11-2** · Acceptance: SpO2 recorded and shown (not scored); reminder timer changed via config only.
**E11-3** · Acceptance: new `action_type` + executor + tool behind the same gate; no change to the approval path.
**E11-4** · Acceptance: order: graph → tools → gates → SQL claim → evals; fits in 10 minutes.

---

## Day-by-day board

| Day | Mahdi | Brother |
|---|---|---|
| **Day 1** | ✅ E0-1, E0-2, E1-1, E1-2, E1-4, E1-7, E1-8 · E0-3, E0-4, E0-7 | E0-5, E7-0, E7-1 |
| **Day 2** | ✅ E1-5, E1-6, E1-1 page refs (done Day 1) · E9-1 if possible | E0-6, E2-1, E2-2, E2-5, E7-2 |
| **Day 3–4** (vaccines, light) | E9-2, E9-3, review E5-1 labels | E5-1, E7-3, E7-4, E2-6 |
| **Day 5** | ✅ E4-1, E4-3, E4-4 (done Day 2) · E4-2 DB part, E8-1, E9-4 → **end-to-end skeleton** | E3-1..4, E2-3, E2-4, E6-2, E7-6 |
| **Day 6** | E4-5, E5-2, E5-3, E5-9, E6-1b | E6-1a, E7-7, E7-8 |
| **Day 7** | E3-5, E4-6, E5-4..6, E6-3, E6-5 | E7-5, E7-10 |
| **Day 8** | E3-6, E4-7, E5-7, E5-8, E5-10, E6-4, E6-6 | E7-9, E7-10, E7-11, E8-2 |
| **Day 9** | E5-11, E8-3..6, E10-2 (code freeze before the final eval run) | E8-7, E10-1, E10-3 · buffer |
| **Day 10** | E11-1, E11-2 | E2-7, E10-4, E10-5 |
| **Day 11 (travel)** | Travel to Nairobi · E11-3, E11-4 | – |
| **Submission day** | Submit · E10-6 | – |
| **Jury day** | Jury: walkthrough + live change | – |

---

## Risks

| Risk | Mitigation |
|---|---|
| Vaccine side effects Day 2–4 | Light tasks only for Mahdi; brother carries UI and data |
| Qwen3 8B slow or unreliable at tool calls | Benchmark on Day 5; `qwen3:4b-instruct` as low-memory option; fixed-code fallback |
| WSO2 or HAPI setup takes longer | Time-box to 1 day; fallback: our own Postgres tables + the official `fetch` MCP server |
| Scope creep | Cuts listed in architecture §13; nothing new after Day 8 |
| Repo does not run on the jury's machine | Clean-machine test Day 10; README states hardware needs |
| Late commit disqualifies | Freeze Day 10; tag the submission commit |

## Decisions log

| Decision |
|---|
| E2-1…E2-3 and E3-1…E3-4 reassigned to M: built and verified on M's side. E2-4 stays with B (routing verified by M; FHIRPath trimming still open). |
| Architecture v4.1 accepted as final. |
| Backlog lives only in this file; no GitHub issues. |
| Repo public from day one; commits use mahdibenamor13@gmail.com. |
| Gateway GET-only (WSO2 0.11.0 uses GET for search and read). |
| SATS manual has no open licence: copy numbers only, attribute, ask EMSSA. |
| Owners rebalanced: Mahdi ≈ 52 h, brother ≈ 45 h. |
| UI follows the "make the agent visible" spec (`web-design.md`). |
| MCP Python SDK pinned to `mcp>=1.9,<2` (v2 renamed FastMCP; LangChain adapters target v1). |
| One reading = one FHIR Observation (vital-signs panel, LOINC components); confirmed colour on `Encounter.priority`. |
| Model choice decided by a Day 5 benchmark: qwen3:8b vs qwen3:30b-a3b (both open weights, both local). |
| `.gitattributes` forces LF checkout: on Windows `core.autocrlf=true` gave `db/init.sh` CRLF endings and `db-init` failed inside the Linux container. |
| **Scope frozen:** UI trimmed to what proves the rubric, simplest form; extras parked (not deleted). Demo = 5/100 points; risk is a repo that does not run. |
| Audit actor: act tools take `actor` (user id from `afya.users`: approving user for `raise_recheck_flag`, the nurse for `record_vitals`, `agent`/`system` when automated) and an optional `run_id`; model-facing read tools have no actor field and log `agent`. An act tool fails if its audit row cannot be written. |
| Queue waiting time from `Encounter.period.start`; re-check intervals are a site rule (`rules/site.yaml`, provisional until the nurse review). |
| Dedup hash rules version = the scoring chart's `chart_id`; proposal payloads must carry `to_colour`. |
| API contract Q1–Q13 accepted as proposed by B. Q6: a nurse or clinician may override the colour to any level, lower included, with a mandatory reason; the agent never downgrades. |
| Patient-reported change (track text: "from a re-check or a patient-reported change") wired end to end: `reported_worsening` on `POST /vitals` → `record_vitals` → `afya.readings.reported_worsening` → agent `trigger` passes `nurse_reported_worsening` to `rules.evaluate_trigger` (trigger `nurse_reported`, existed in E1-6 but had no input). Coded yes/no, never free text; a reading still needs at least one value (one reading = one Observation). B, Day 8. |

## Parking lot (after Day 8, not before)

- Child SATS charts as a real feature (beyond the rehearsal)
- Hash chain on the audit log
- Real sign-in (OIDC)
- Live push updates instead of polling
- W11 installable PWA + connection-lost banner, W12 offline vitals queue

### Parked UI extras (from `web-design.md`, kept in case there is spare time after Day 8)

| Was | Item | Est. | Needs |
|---|---|---|---|
| E7-1 | Wall mode for the clinic TV | 1 h | E7-1 |
| E7-4 | Evidence sparklines drawn over shaded SATS bands (replaces the table) | 1.5 h | E6-5 + bands in `/visits/{id}/timeline` |
| E7-5 | Replay button on the agent trace | 2 h | E7-5 |
| E7-7 | Animated gate stepper | 1 h | E7-7 |
| E7-9 / E6-6 | Simulated clock ×1/×10/×30 (`POST /demo/clock`) | 1 h B + 1 h M | E6-6 |
| E7-12 | W7 live cost & latency badge | 0.5 h | E6-5 |
| E7-13 | W8 UI in English, Kiswahili, French | 3 h | E7-10 |
| E7-14 | W9 keyboard shortcuts | 1 h | E7-10 |
| E7-15 / E6-7 | W10 shift handover sheet (`GET /handover`) | 1.5 h B + 0.5 h M | E7-10 |

---

## Draft email to EMSSA (E0-3)

> Subject: Permission to reference SATS 2012 score bands in an open-source research prototype
>
> Dear EMSSA team,
>
> We are building a non-commercial research prototype for the African Agentic AI Challenge (final in Nairobi). It helps triage nurses notice patients who may be getting worse while waiting. It uses synthetic data only and is not for clinical use.
>
> We would like to include the adult TEWS score bands and colour categories from the SATS Training Manual (2012) as numeric values in a configuration file. We would attribute them to EMSSA with a link to emssa.org.za/sats and copy no manual text. Could you confirm whether this is acceptable, and under what licence the manual may be used?
>
> Kind regards,
> Mahdi Ben Amor
