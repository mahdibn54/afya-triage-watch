# Afya Triage Watch: Project Backlog (BMAD style)

> **This file is the only backlog.** There are no GitHub issues. Every task, its status and its details live
> here. Update the story's status (and its notes, if needed) in the same pull request that does the work.

**Architecture:** v4.1, accepted 2026-11-05 ([`architecture-v4.1.pdf`](architecture-v4.1.pdf))
**Challenge:** African Agentic AI Challenge, Healthcare track "The Triage Desk", sub-theme *Deterioration Watch*
**Repo:** https://github.com/mahdibn54/afya-triage-watch
**Team:** **M** = Mahdi (agent core) · **B** = Brother (product, infra, data, proof)
**Deadlines:** code freeze **14 Nov** · submission **16 Nov** (Nairobi) · jury **17 Nov**
**Budget:** $0, plus OpenRouter capped at $10–20

**Status:** `[ ]` to do · `[~]` in progress / drafted · `[x]` done · `[!]` blocked (say why in Notes)

**Progress:** 9 done · 11 drafted · 67 to do · 0 blocked · 87 stories · last updated **2026-11-05**

---

## How we work

1. Pick the next story for your name on the day board (bottom of this file). Check its dependencies are `[x]`.
2. Create a branch named after the story: `E7-3-approval-card`.
3. Do the work, then meet the story's **Acceptance** bullets and the Definition of Done.
4. In the same PR, set the story's status to `[x]` here and add anything useful to its **Notes**.
5. The other person reviews; merge only when CI is green.
6. Daily 15-minute check-in: what's done, what's next, what's blocked (`[!]` + reason here).
7. Nothing new after **12 Nov**. Late ideas go to "Parking lot" at the end.

## Who does what

Remaining estimate: **Mahdi ≈ 53 h** (light on 7–8 Nov because of vaccines) · **Brother ≈ 50 h**.

| Mahdi: the agent core (explained in the live review) | Brother: product, infra, data and proof |
|---|---|
| SATS rules and scorer | Next.js nurse UI, approval card, notices, audit viewer, sign-in switcher (E7) |
| afya-mcp tools (E4) | docker-compose, networks, nginx gateway, clean-machine test (E2) |
| LangGraph agent: signs, investigate loop, watch loop, fallbacks (E5-2…E5-11) | Postgres: run and verify roles, schema, triggers, checkpoints (E3-1…E3-4) |
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
| E0-1 | [x] | Public repo, MIT licence, README, `.gitignore`, `.env.example` | M | 5 Nov | 0.5 h | – |
| E0-2 | [x] | SATS NOTICE and licence carve-out for `rules/charts/` | M | 5 Nov | 0.5 h | E0-1 |
| E0-3 | [ ] | Send the email to EMSSA (draft at the end of this file) | M | 5 Nov | 0.3 h | – |
| E0-4 | [ ] | Ask Clinton: exact submission time, format, brother listed as team member | M | 5 Nov | 0.2 h | – |
| E0-5 | [~] | Agree the API contract | M+B | 5 Nov | 1 h | – |
| E0-6 | [ ] | CI on every push | B | 6 Nov | 1 h | E0-1 |
| E0-7 | [ ] | Invite brother as collaborator (`dhekerbenamor@gmail.com`) | M | 5 Nov | 0.1 h | E0-1 |

**E0-1** · Files: `LICENSE`, `README.md`, `.gitignore`, `.env.example` · Acceptance: repo public; `.env` ignored. · Notes: done in commit `1645177`. Commits use mahdibenamor13@gmail.com.
**E0-2** · Files: `rules/charts/NOTICE.md`, licence line in `LICENSE` and `README.md` · Acceptance: chart folder explicitly outside MIT, EMSSA attributed, no manual text copied.
**E0-3** · Acceptance: email sent; reply (or none) recorded here. Until permission, the chart folder stays "non-commercial research only".
**E0-4** · Acceptance: answers recorded here: deadline timestamp + timezone, required deliverables, team listing.
**E0-5** · Files: `docs/api.md` · Acceptance: both agree; brother can build the UI against fake JSON matching it. · Notes: draft written 5 Nov.
**E0-6** · Files: `.github/workflows/ci.yml` · Acceptance: on push and PR runs `ruff`, `mypy`, `pytest` (mcp + api) and `npm run build` (web); red CI blocks merge.
**E0-7** · Acceptance: invitation accepted. · Notes: needs GitHub's email verification (sudo mode) by Mahdi first. GitHub personal repos have no "maintainer" role: collaborator = push, merge, manage issues/labels.

---

## E1 · SATS rules and scoring (fixed code, no LLM)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E1-1 | [x] | Chart registry with the adult 2012 chart as YAML | M | 5 Nov | 1.5 h | E0-2 |
| E1-2 | [x] | Sign allow-list (2 RED, 12 ORANGE, 5 YELLOW) with own glosses | M | 5 Nov | 0.5 h | E1-1 |
| E1-3 | [~] | Chart selection by age/height; "no chart" otherwise | M | 6 Nov | 1 h | E1-1 |
| E1-4 | [x] | Pure scorer `score(values, chart)` | M | 5 Nov | 1.5 h | E1-1 |
| E1-5 ✅ | [x] | Plausibility limits in YAML (provisional) | M | 5 Nov | 0.5 h | – |
| E1-6 ✅ | [x] | Trigger rule in code | M | 5 Nov | 1 h | E1-4 |
| E1-7 | [x] | Fixture tests (11 patients from architecture §11) | M | 5 Nov | 1 h | E1-4 |
| E1-8 | [x] | Band-edge tests from an independent reading of the chart | M | 5 Nov | 1 h | E1-4 |

**E1-1** · Files: `rules/charts/sats_adult_2012.yaml` · Acceptance: bands, colours, target times; numbers match the EMSSA 2012 adult chart. · Notes: manual page references added 5 Nov (`source_pages`: target times pp. 6–7, adult chart and signs p. 8, adult TEWS pp. 26–27).
**E1-2** · Acceptance: codes match the verified adult discriminator list (architecture §2); glosses are our own words.
**E1-3** · Files: `mcp/afya_mcp/rules.py` (`select_chart`) · Acceptance: adult = over 12 y or over 150 cm; otherwise `NoChartForPatient` → UI notice "no chart for this patient yet". · Notes: function + test done; still to wire into `compute_tews` (E4-3).
**E1-4** · Acceptance: returns tews, colour by TEWS, signs implied by inputs, final colour = highest of TEWS and signs, points and cited IDs per input; missing inputs reported, never guessed.
**E1-5** · Files: `rules/plausibility.yaml` · Acceptance: limits loaded by code; outside → nothing saved, re-measure notice. · Notes: `load_plausibility` + `check_plausible` done 5 Nov with tests (HR 400, °F temperature, etc.); values provisional until reviewed with the nurse (E9-4). The "nothing saved" part is enforced in `record_vitals` (E4-2).
**E1-6** · Acceptance: proposal only on (a) colour rise, (b) current ORANGE/RED sign, (c) nurse-reported worsening; smaller changes logged only; never downgrades. Tests for B→B2, M1→M2, improvement, C (confused). · Notes: `evaluate_trigger` done 5 Nov: trigger reference is the colour a nurse last **confirmed**; urgent = ORANGE/RED signs only (a YELLOW sign alone is logged); incomplete scores still trigger and say "lower bound"; unknown sign codes raise. 20 tests in `mcp/tests/test_plausibility_trigger.py`.
**E1-7 / E1-8** · Files: `mcp/tests/test_rules.py` · Notes: 44 tests passing on 5 Nov (64 in total with E1-5/E1-6).

---

## E2 · Infrastructure (one command)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E2-1 | [~] | docker-compose with all services and health checks | B | 6 Nov | 3 h | E0-5 |
| E2-2 | [~] | Private networks; only the UI published on 127.0.0.1:3000 | B | 6 Nov | 1 h | E2-1 |
| E2-3 | [~] | nginx gateway, GET only | B | 9 Nov | 1 h | E2-2 |
| E2-4 | [ ] | WSO2 config and FHIRPath response trimming | B | 9 Nov | 1 h | E2-2 |
| E2-5 | [ ] | Host Ollama for the GPU, bound to the Docker bridge | B | 6 Nov | 0.5 h | – |
| E2-6 | [ ] | Seed job loading the 20 synthetic patients into HAPI | B | 8 Nov | 1 h | E5-1 |
| E2-7 | [ ] | Clean-machine test | B | 14 Nov | 1 h | all |

**E2-1** · Files: `docker-compose.yml` · Acceptance: `docker compose up --build` starts postgres → db-init → lg-init → hapi → gateway → wso2-fhir-mcp → afya-mcp → api (→ web with `--profile web`) without manual steps. · Notes: drafted by M on 5 Nov; `docker compose config` valid. **To verify on first run:** HAPI H2 volume path (`/app/target`), lg-init grants, `wso2-fhir-mcp` MCP path (`/mcp`).
**E2-2** · Acceptance: networks `app`, `mcp`, `fhir_ro`, `fhir_rw` internal; only `web` published. Test: `docker compose exec wso2-fhir-mcp` cannot resolve `hapi`. · Notes: drafted.
**E2-3** · Files: `gateway/nginx.conf` · Acceptance: GET/HEAD only; 403 for `;` `..` `%2e` `%2f` `%3b` `%5c` `$` in the path; method-override headers cleared; reference params like `subject=Patient%2F1` in the query still work. · Notes: `nginx -t` OK on 5 Nov. WSO2 0.11.0 uses GET for search and read (checked in its source).
**E2-4** · Acceptance: WSO2 reaches HAPI only via `http://gateway/fhir`; `FHIR_SERVER_DISABLE_AUTHORIZATION=True` only on the private network; a FHIRPath filter returns id, code, value, unit, time.
**E2-5** · Acceptance: `ollama pull qwen3:8b qwen3:4b-instruct qwen3:30b-a3b`; `OLLAMA_HOST=172.17.0.1:11434` (Docker bridge, not 0.0.0.0); API reaches it via `host.docker.internal`. Record tokens/s here.
**E2-6** · Files: `seed/` · Acceptance: idempotent; loads the 20 patients and their visits into HAPI and `afya.visits`.
**E2-7** · Acceptance: fresh clone on another machine or user → README steps only → full P-014 demo works. Time it and note it here.

---

## E3 · PostgreSQL data layer

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E3-1 | [~] | db-init runs the schema as `afya_owner` | B | 9 Nov | 1.5 h | E2-1 |
| E3-2 | [~] | Roles: `afya_app` least privilege | B | 9 Nov | 0.5 h | E3-1 |
| E3-3 | [~] | Audit log append-only (grants + triggers) | B | 9 Nov | 0.5 h | E3-1 |
| E3-4 | [~] | LangGraph checkpoints in schema `lg` | B | 9 Nov | 0.5 h | E3-1 |
| E3-5 | [ ] | Approve, claim, mark-done, startup-sweep queries | M | 11 Nov | 2 h | E3-1 |
| E3-6 | [ ] | Dedup key and insert | M | 12 Nov | 1 h | E3-1 |

**E3-1** · Files: `db/init.sh`, `db/schema.sql` · Acceptance: runs on every start without errors (idempotent). · Notes: DDL written 5 Nov; B runs and verifies it.
**E3-2** · Acceptance: `afya_app` is LOGIN, NOSUPERUSER, not a member of `afya_owner`, has no CREATE; owner and superuser passwords exist only in `db-init`.
**E3-3** · Acceptance: as `afya_app`, UPDATE, DELETE and TRUNCATE on `afya.audit_log` all fail; INSERT works (identity column needs no sequence grant: confirm). Wording: "append-only for the application role".
**E3-4** · Files: `api/afya_api/lg_setup.py` · Acceptance: `lg-init` creates the checkpoint tables as owner; `afya_app` can read/write them but not alter them.
**E3-5** · Acceptance: approve = role check (403) then `UPDATE … WHERE status='pending'` (0 rows → 409) + audit + command in **one transaction**; claim = not claimed, not expired, still the latest reading, proposal approved; resume = claimed, not done, attempts < 5; startup sweep resumes approved-not-done. SQL in architecture Appendix A.
**E3-6** · Acceptance: `UNIQUE(visit_id, trigger, evidence_hash)`; hash = sorted obs IDs + sign codes + rules version (never the model's quote text); `INSERT … ON CONFLICT DO NOTHING RETURNING`.

---

## E4 · afya-mcp server (6 tools)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E4-1 | [~] | Server with two mounts: `/read/mcp` and `/act/mcp` | M | 9 Nov | 1 h | – |
| E4-2 | [ ] | `record_vitals` | M | 9 Nov | 2 h | E3-1 |
| E4-3 | [ ] | `compute_tews` | M | 9 Nov | 1 h | E1-4 |
| E4-4 | [ ] | `check_deterioration` | M | 10 Nov | 1.5 h | E4-3 |
| E4-5 | [ ] | `get_queue_state` | M | 10 Nov | 1.5 h | E3-1 |
| E4-6 | [ ] | `raise_recheck_flag` via the executor registry | M | 11 Nov | 2.5 h | E3-5 |
| E4-7 | [ ] | `notify_staff` | M | 12 Nov | 1 h | E3-1 |
| E4-8 | [ ] | Audit every tool call | M | 9–12 Nov | incl. | E3-3 |

**E4-1** · Files: `mcp/afya_mcp/server.py` · Acceptance: `/healthz` OK; read tools only on `/read/mcp`, act tools only on `/act/mcp`. · Notes: skeleton with stubs written 5 Nov.
**E4-2** · Acceptance: input = LOINC-coded list + idempotency key; plausibility check first; FHIR conditional create with `identifier=urn:afya:req|<key>`; updates `visits.latest_obs_id` in the same transaction; retry returns the same IDs.
**E4-3** · Acceptance: input = observation ID only; reads values from HAPI itself; selects the chart (E1-3); returns score, colour, chart_id and cited IDs.
**E4-4** · Acceptance: compares with earlier scored readings; returns change, trigger type (E1-6) and cited records.
**E4-5** · Acceptance: minutes waited vs SATS target per patient; overdue re-checks (site intervals from E9-4, labelled "site rule"); unread proposals with age.
**E4-6** · Acceptance: input = command ID only; claim (E3-5) → FHIR conditional create Flag (identifier derived from the command) + Encounter priority → mark done + audit in one transaction; safe on retry or crash.
**E4-7** · Acceptance: fixed text only (restates an existing proposal's colour and cited IDs, or "vitals due"); never changes the queue; audited.
**E4-8** · Acceptance: every call writes inputs, outputs, actor, run_id and latency to `audit_log`.

---

## E5 · Agent (LangGraph)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E5-1 | [ ] | 20 synthetic patients (B writes, M reviews labels) | B | 7–8 Nov | 3 h | E1-7 |
| E5-2 | [ ] | Event-run graph, one thread per vitals event | M | 10 Nov | 3 h | E4-* |
| E5-3 | [ ] | `map_signs` (model call A) | M | 10 Nov | 2 h | E1-2 |
| E5-4 | [ ] | `investigate` (model call B, read-only loop) | M | 11 Nov | 3 h | E5-2 |
| E5-5 | [ ] | Urgency rule: the model can only add | M | 11 Nov | 0.5 h | E5-4 |
| E5-6 | [ ] | Rationale filter | M | 11 Nov | 1 h | E5-4 |
| E5-7 | [ ] | Watch loop and immediate RED/ORANGE notifications | M | 12 Nov | 2 h | E4-7 |
| E5-8 | [ ] | Supersession and "not reviewed" | M | 12 Nov | 1 h | E5-2 |
| E5-9 | [ ] | Model settings and limits | M | 10 Nov | 1 h | E2-5 |
| E5-10 | [ ] | Model-down fallback | M | 12 Nov | 0.5 h | E5-2 |
| E5-11 | [ ] | OpenRouter client (guarded) | M | 13 Nov | 1 h | E5-9 |

**E5-1** · Files: `evals/fixtures/synthetic/*.json` · Acceptance: 8 positive (YELLOW→ORANGE, GREEN→YELLOW, ORANGE→RED, sign-only SOB, sign-only confused, gradual rise over 3 readings, Swahili-only complaint, code-switched or misspelt complaint) and 12 negative (stable, B→B2, M1→M2, improvement, first visit, HR 400, temperature in °F, missing mobility, negation, injection, child, boundary HR 100→101); invented complaints in English, Swahili and French; ground truth from the scorer; split 6 tuning / 14 held out.
**E5-2** · Acceptance: validate → record → score → deteriorate → map_signs → trigger → investigate → proposal + `interrupt()` → fixed executor; thread ID `visit:obs_id`; checkpoints in Postgres.
**E5-3** · Acceptance: JSON-schema output, enum codes, `current|other`, quote max 15 words; code keeps a sign only if it is on the allow-list, `current`, and its quote really appears in the complaint; drops are logged; prompt in architecture Appendix B.
**E5-4** · Acceptance: tools offered = WSO2 search/read + compute_tews (earlier readings), check_deterioration, get_queue_state; max 4 calls, then `submit_decision`; ToolNode built from the same filtered list (a forged write-tool call is refused); receives sign codes, never quotes; FHIR trimmed to code, value, unit, time, id.
**E5-5** · Acceptance: code always creates a proposal on a trigger; model can add re-measure, extra trigger or missing-value request, never remove.
**E5-6** · Acceptance: prompt forbids conditions, causes, drugs, doses, treatments; denylist check (sepsis, pneumonia, malaria, infection, diagnos*, likely, suspect, give, administer, mg, antibiotic, paracetamol…); failing text replaced by a code-built sentence and logged.
**E5-7** · Acceptance: RED/ORANGE proposals notify at creation; loop every `WATCH_INTERVAL_SECONDS` (60; 30 in demo): vitals-due reminders, unread ORANGE after 5 min and RED after 1 min → `notify_staff`; nothing in the queue changes.
**E5-8** · Acceptance: newer vitals mark the old proposal `superseded`; if never reviewed it stays visible as "not reviewed" until a nurse acknowledges it.
**E5-9** · Acceptance: on 9 Nov benchmark `qwen3:8b` (GPU) vs `qwen3:30b-a3b` (MoE, 3B active, CPU + 30 GB RAM) on the 6 tuning patients: sign accuracy, tool-call validity, seconds per run; pick the default by these numbers and record them in Notes. Settings for the chosen model: `think:false`, `num_ctx` 8192, `num_predict` 384, temperature 0 (signs) / 0.2 (investigate), top_p 0.8, top_k 20, seed logged; 60 s per call, 240 s per run; one retry on invalid JSON; timeout → rules only; circuit breaker (2 failures → skip model 5 min); warm-up call at start.
**E5-10** · Acceptance: with the model off, score, trigger and proposal still work; card shows "no model" and the raw complaint.
**E5-11** · Acceptance: `ALLOW_REMOTE_MODEL=false` by default; refuses input not from `evals/fixtures/synthetic/`; provider pinned; records billed `usage.cost`; key only in `.env`.

---

## E6 · API (FastAPI)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E6-1a | [ ] | Read endpoints: `/login-as`, `/me`, `/queue`, `/audit` | B | 9–10 Nov | 1.5 h | E0-5 |
| E6-1b | [ ] | Write endpoints: `/vitals`, `/proposals`, approve, reject | M | 10–11 Nov | 1.5 h | E0-5 |
| E6-2 | [ ] | Demo sign-in session | B | 9 Nov | 1 h | E6-1a |
| E6-3 | [ ] | Approve = one transaction, then resume the graph | M | 11 Nov | 1.5 h | E3-5 |
| E6-4 | [ ] | Startup sweep | M | 12 Nov | 0.5 h | E3-5 |
| E6-5 | [ ] | UI data endpoints: visit timeline, run trace, proposal gates | M | 11 Nov | 2.5 h | E4-8 |
| E6-6 | [ ] | Demo endpoint: load the P-014 scenario (DEMO_MODE only) | M | 12 Nov | 0.5 h | E5-7 |

**E6-1a / E6-1b** · Files: `api/afya_api/` · Acceptance: match `docs/api.md` exactly; JSON errors with clear messages.
**E6-2** · Acceptance: only when `DEMO_MODE=1`; signed session cookie (SameSite=Strict, secret from `SESSION_SECRET`); user always from the session, never the body; `auth: demo_switcher` in audit rows.
**E6-3** · Acceptance: body = colour, signs kept, override reason; role check 403 → single-use update 409 → decision + audit + command in one transaction → resume LangGraph with the command ID.
**E6-4** · Acceptance: on start, resumes approved commands not done (idempotent).
**E6-5** · Acceptance: `GET /visits/{id}/timeline` (readings with per-input points and record IDs), `GET /runs/{run_id}/trace` (ordered steps: server ours/borrowed, tool or model, trimmed args, result summary, latency, tokens, cost), `GET /proposals/{id}/gates` (time per gate step + refused attempts); all built from `audit_log` and FHIR, no new state.
**E6-6** · Acceptance: `POST /demo/scenario` loads P-014 and `POST /demo/scenario/next` adds its next reading; both return 404 unless `DEMO_MODE=1`.

---

## E7 · Nurse UI (Next.js), design spec in [`web-design.md`](web-design.md)

Scope frozen 2026-11-05: only the UI that proves the rubric, in its simplest form. Extras are parked at the end of this file.

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E7-0 | [ ] | App setup: Next.js + Tailwind + shadcn/ui + TanStack Query + generated API types + Dockerfile + `/api` proxy | B | 5 Nov | 1.5 h | – |
| E7-1 | [ ] | **W1** Waiting-room board with time-to-target bars | B | 5–6 Nov | 3 h | E0-5 |
| E7-2 | [ ] | Vitals entry form | B | 6 Nov | 2 h | E0-5 |
| E7-3 | [ ] | Approval card + **W3** complaint with highlighted quotes | B | 7 Nov | 3.5 h | E0-5 |
| E7-4 | [ ] | **W2** Evidence table on the approval card | B | 8 Nov | 1.5 h | E7-3 |
| E7-5 | [ ] | **W5** Agent trace as a plain list | B | 11 Nov | 2 h | E6-5 |
| E7-6 | [ ] | "Sign in as…" switcher with DEMO badge | B | 9 Nov | 1 h | E6-2 |
| E7-7 | [ ] | **W4** Gate steps as a simple list of ticks | B | 10 Nov | 1 h | E6-5 |
| E7-8 | [ ] | Notices | B | 10 Nov | 2 h | E7-1 |
| E7-9 | [ ] | **W6** Demo scenario loader | B | 12 Nov | 1 h | E6-6 |
| E7-10 | [ ] | Wire everything to the real API, remove fake JSON | B | 11–12 Nov | 2 h | E6-1a, E6-1b |
| E7-11 | [ ] | Playwright end-to-end test of the P-014 flow | B | 12 Nov | 1.5 h | E7-10 |

**E7-0** · Files: `web/` · Acceptance: `npx create-next-app@latest` (TypeScript, App Router); Tailwind + shadcn/ui; TanStack Query; `openapi-typescript` generates `web/src/api/types.ts` from FastAPI's `/openapi.json`; production build on port 3000; `/api/*` proxied to `API_INTERNAL_URL`; enabled with `--profile web`.
**E7-1** · Acceptance: one row per waiting patient: confirmed colour chip with label and shape (■ ▲ ● ○), time-to-target bar filling towards the SATS target with a countdown, flags, notices; sorted by time left; "last updated n s ago"; works on fake JSON first; tablet-sized touch targets.
**E7-2** · Acceptance: coded fields (RR, HR, SBP, temperature, SpO2, mobility, consciousness, trauma) + free-text complaint; sends an idempotency key; shows the re-measure notice inline.
**E7-3** · Acceptance: proposed vs current colour; complaint shown with matched phrases highlighted (sliced from `quote_span`, plain text only) and linked to sign chips; "other" mentions greyed with the reason; sign tickboxes; colour override + reason; approve/reject; 403/409 shown clearly.
**E7-4** · Acceptance: a table of the cited readings: vital, previous value → new value, points before → after, record ID; rows that moved into a higher band are emphasised.
**E7-5** · Acceptance: per run, an ordered list: tool calls tagged **ours** / **borrowed (WSO2)**, model calls with tokens and latency, the decision with cited IDs; the manager can read it; used in the demo video.
**E7-6** · Acceptance: nurse / clinician / manager; visible DEMO badge; the manager sees no approve button anywhere.
**E7-7** · Acceptance: a list of ticks Proposed → Paused for nurse → Confirmed by <name> → Command claimed → Written to record → Audited, each with its time; refused attempts listed with role and time.
**E7-8** · Acceptance: `remeasure`, `no_chart`, `not_reviewed`, `instruction_like_text`, `vitals_due`, `clinician_reminded`, `model_unavailable`, each with clear wording from the say/avoid table.
**E7-9** · Acceptance: only with `DEMO_MODE=1`: a button loads the P-014 scenario and another adds its next reading. For the video, set `WATCH_INTERVAL_SECONDS` and the unread-reminder time low in `.env`.
**E7-10** · Acceptance: the full P-014 flow works by clicking only; nothing changes colour before approval.
**E7-11** · Acceptance: Playwright script runs P-014 end to end (vitals → proposal → manager refused → nurse confirms → ORANGE with flag) and passes in CI against the compose stack.

---

## E8 · Evaluation (EVALS.md)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E8-1 | [ ] | Eval harness `make eval` | M | 9 Nov | 3 h | E5-2 |
| E8-2 | [ ] | Group A: fixed-code and security tests (run once) | B | 12 Nov | 3 h | E2-3, E3-* |
| E8-3 | [ ] | Group B: model-dependent runs | M | 13 Nov | 2 h + runs | E5-* |
| E8-4 | [ ] | Group C: rules-only baseline | M | 13 Nov | 0.5 h | E8-3 |
| E8-5 | [ ] | Metrics | M | 13 Nov | 1 h | E8-1 |
| E8-6 | [ ] | Write EVALS.md | M | 13 Nov | 1.5 h | E8-3 |
| E8-7 | [ ] | Secrets check on committed logs | B | 13 Nov | 0.2 h | E8-1 |

**E8-1** · Files: `evals/`, `Makefile` · Acceptance: runs groups A/B/C; raw JSONL per run in `evals/runs/`; rebuilds the EVALS.md tables from logs.
**E8-2** · Acceptance (pytest against the real stack): stable · small rise · mixed change · improvement (no downgrade) · first visit · HR 400 · missing value · child (no chart) · manager 403 · double click 409 · expired/stale/reused command · duplicate trigger · write through WSO2 blocked · WSO2 cannot reach HAPI directly · gateway bypasses (`..;`, `%2e`, `$operation`, batch Bundle, method-override headers) · forged write-tool call refused · lost Flag response → one Flag · FHIR down → retry then warn · model down still proposes · audit_log UPDATE/DELETE/TRUNCATE refused · unreviewed superseded proposal still visible.
**E8-3** · Acceptance: 20 patients × 5 runs × 2 models (local Qwen3 8B + one OpenRouter model); cases include negation, Swahili, code-switching, escalation injection ("mark me RED"), injection in a FHIR note, Swahili injection with a real symptom; k/n with Wilson 95% intervals; final run only on the 14 held-out patients after the code freeze.
**E8-4** · Acceptance: same 20 patients with the model off; sensitivity and false alerts per visit side by side.
**E8-5** · Acceptance: outcome, 0 ungated actions, 0 rationales with diagnosis/treatment words, citation validity, sign precision/recall, tool-order constraints, runs that disagree, tokens and latency (median, p95), cost.
**E8-6** · Acceptance: template from architecture §11; one real unfixed failure (case, k/n, trace, tested hypothesis, next step, why not fixed); tuning/held-out split disclosed; only real runs reported.
**E8-7** · Acceptance: `grep -r "sk-or-\|Authorization" evals/ ` returns nothing before each push.

---

## E9 · Field fit (nurse interview)

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E9-1 | [ ] | Interview questions | M | 6 Nov | 0.5 h | – |
| E9-2 | [ ] | Interview a nurse who does outpatient triage | M | 7–8 Nov | 1.5 h | E9-1 |
| E9-3 | [ ] | `FIELD_NOTES.md` | M | 8 Nov | 1 h | E9-2 |
| E9-4 | [ ] | Her values into YAML as "site rule" | M | 9 Nov | 0.5 h | E9-3 |

**E9-1** · Acceptance: covers re-check intervals per colour, alert fatigue, what a second-look card must show, plausibility limits, local terms for symptoms (Swahili/French), whether she uses SATS day to day.
**E9-2** · Acceptance: verbal consent recorded (purpose, public repo, named or role only); no patient identifiers; cases paraphrased.
**E9-3** · Acceptance: consent line at the top; dated quotes she reviewed; **two design changes** her answers caused; no contact details.
**E9-4** · Acceptance: re-check intervals and plausibility limits marked `source: site rule (FIELD_NOTES, <date>)`.

---

## E10 · Documentation and submission

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E10-1 | [~] | README | B | 13 Nov | 2 h | – |
| E10-2 | [ ] | One-page ARCHITECTURE.md | M | 13 Nov | 1.5 h | – |
| E10-3 | [ ] | 300-word description | B | 13 Nov | 0.5 h | – |
| E10-4 | [ ] | Demo video (under 3 min, unedited) | B | 14 Nov | 2 h | E2-7 |
| E10-5 | [ ] | Pitch deck + workflow GIF | B | 14 Nov | 2 h | – |
| E10-6 | [ ] | Tag the submitted commit | M | 16 Nov | 0.1 h | all |

**E10-1** · Acceptance: one-command run, hardware note, honest gaps, "path to a pilot" paragraph (Kenya DPA 2019, no compliance claim), licence split, say/avoid wording. · Notes: first version written 5 Nov.
**E10-2** · Acceptance: one page: agent shape, MCP servers built vs borrowed and why, Postgres → FHIR write order, "append-only for the app role".
**E10-3** · Acceptance: what it does, sub-theme, the facility and workflow it serves; ~300 words; English.
**E10-4** · Acceptance: P-014 run with tool calls on screen, nurse confirms, one recovery (HR 400), a watch-loop reminder; public on YouTube or Vimeo.
**E10-5** · Acceptance: 5–7 slides: problem, how it works, safety gates, evals, path to a pilot.
**E10-6** · Acceptance: `git tag submission-2026-11-16`; no commit after the deadline.

---

## E11 · Live review readiness

| ID | Status | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|---|
| E11-1 | [ ] | Rehearse "add the child chart" in 15 min | M | 14 Nov | 1 h | E1-3 |
| E11-2 | [ ] | Rehearse "add SpO2" and "change the reminder timer" | M | 14 Nov | 0.5 h | E4-2, E5-7 |
| E11-3 | [ ] | Rehearse "add referral routing" | M | 15 Nov | 1 h | E4-6 |
| E11-4 | [ ] | 10-minute code walkthrough script | M | 15 Nov | 1 h | – |

**E11-1** · Acceptance: new YAML in `rules/charts/` + selection works + 2 tests, under 15 minutes, timed.
**E11-2** · Acceptance: SpO2 recorded and shown (not scored); reminder timer changed via config only.
**E11-3** · Acceptance: new `action_type` + executor + tool behind the same gate; no change to the approval path.
**E11-4** · Acceptance: order: graph → tools → gates → SQL claim → evals; fits in 10 minutes.

---

## Day-by-day board

| Day | Mahdi | Brother |
|---|---|---|
| **5 Nov** | ✅ E0-1, E0-2, E1-1, E1-2, E1-4, E1-7, E1-8 · E0-3, E0-4, E0-7 | E0-5, E7-0, E7-1 |
| **6 Nov** | ✅ E1-5, E1-6, E1-1 page refs (done 5 Nov) · E9-1 if possible | E0-6, E2-1, E2-2, E2-5, E7-2 |
| **7–8 Nov** (vaccines, light) | E9-2, E9-3, review E5-1 labels | E5-1, E7-3, E7-4, E2-6 |
| **9 Nov** | E4-1..3, E8-1, E9-4 → **end-to-end skeleton** | E3-1..4, E2-3, E2-4, E6-2, E7-6 |
| **10 Nov** | E4-4, E4-5, E5-2, E5-3, E5-9, E6-1b | E6-1a, E7-7, E7-8 |
| **11 Nov** | E3-5, E4-6, E5-4..6, E6-3, E6-5 | E7-5, E7-10 |
| **12 Nov** | E3-6, E4-7, E5-7, E5-8, E5-10, E6-4, E6-6 | E7-9, E7-10, E7-11, E8-2 |
| **13 Nov** | E5-11, E8-3..6, E10-2 (code freeze before the final eval run) | E8-7, E10-1, E10-3 · buffer |
| **14 Nov** | E11-1, E11-2 | E2-7, E10-4, E10-5 |
| **15 Nov** | Travel to Nairobi · E11-3, E11-4 | – |
| **16 Nov** | Submit · E10-6 | – |
| **17 Nov** | Jury: walkthrough + live change | – |

---

## Risks

| Risk | Mitigation |
|---|---|
| Vaccine side effects 6–8 Nov | Light tasks only for Mahdi; brother carries UI and data |
| Qwen3 8B slow or unreliable at tool calls | Benchmark on 9 Nov; `qwen3:4b-instruct` as low-memory option; fixed-code fallback |
| WSO2 or HAPI setup takes longer | Time-box to 1 day; fallback: our own Postgres tables + the official `fetch` MCP server |
| Scope creep | Cuts listed in architecture §13; nothing new after 12 Nov |
| Repo does not run on the jury's machine | Clean-machine test 14 Nov; README states hardware needs |
| Late commit disqualifies | Freeze 14 Nov; tag the submission commit |

## Decisions log

| Date | Decision |
|---|---|
| 2026-11-05 | Architecture v4.1 accepted as final. |
| 2026-11-05 | Backlog lives only in this file; no GitHub issues. |
| 2026-11-05 | Repo public from day one; commits use mahdibenamor13@gmail.com. |
| 2026-11-05 | Gateway GET-only (WSO2 0.11.0 uses GET for search and read). |
| 2026-11-05 | SATS manual has no open licence: copy numbers only, attribute, ask EMSSA. |
| 2026-11-05 | Owners rebalanced: Mahdi ≈ 52 h, brother ≈ 45 h. |
| 2026-11-05 | UI follows the "make the agent visible" spec (`web-design.md`). |
| 2026-11-05 | Model choice decided by a 9 Nov benchmark: qwen3:8b vs qwen3:30b-a3b (both open weights, both local). |
| 2026-11-05 | **Scope frozen:** UI trimmed to what proves the rubric, simplest form; extras parked (not deleted). Demo = 5/100 points; risk is a repo that does not run. |

## Parking lot (after 12 Nov, not before)

- Child SATS charts as a real feature (beyond the rehearsal)
- Hash chain on the audit log
- Real sign-in (OIDC)
- Live push updates instead of polling
- W11 installable PWA + connection-lost banner, W12 offline vitals queue

### Parked UI extras (from `web-design.md`, kept in case there is spare time after 12 Nov)

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
> We are building a non-commercial research prototype for the African Agentic AI Challenge (Nairobi, November 2026). It helps triage nurses notice patients who may be getting worse while waiting. It uses synthetic data only and is not for clinical use.
>
> We would like to include the adult TEWS score bands and colour categories from the SATS Training Manual (2012) as numeric values in a configuration file. We would attribute them to EMSSA with a link to emssa.org.za/sats and copy no manual text. Could you confirm whether this is acceptable, and under what licence the manual may be used?
>
> Kind regards,
> Mahdi Ben Amor
