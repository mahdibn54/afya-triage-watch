# Afya Triage Watch: Project Backlog (BMAD style)

**Architecture:** v4.1, accepted 2026-11-05 (`Afya_Triage_Watch.pdf`)
**Challenge:** African Agentic AI Challenge, Healthcare track "The Triage Desk", sub-theme *Deterioration Watch*
**Team:** **M** = Mahdi (Python, agent, data) · **B** = Brother (Next.js, infra, pitch)
**Deadlines:** code freeze **14 Nov** · submission **16 Nov** (Nairobi) · jury **17 Nov**
**Budget:** $0, plus OpenRouter capped at $10–20

Status keys: `[ ]` to do · `[~]` in progress · `[x]` done · `[!]` blocked

---

## 0. Definition of Done (applies to every story)

- [ ] Code merged to `main`. CI green: lint, type check, tests.
- [ ] Every action is logged in `audit_log` with actor, inputs, outputs, time and model tokens.
- [ ] No real patient data. Fixtures are synthetic only.
- [ ] Nothing changes a patient's colour or queue position without a nurse or clinician confirming.
- [ ] README updated if run steps or env vars changed.
- [ ] Wording follows the say/avoid table in PDF §14: no "diagnose", "AI triage", "escalate", "safe", "validated".

---

## Epic E0: Project setup and governance

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E0-1 | Create the public GitHub repo with MIT `LICENSE`, `README` skeleton, `.gitignore` (incl. `.env`), `.env.example` | M | 5 Nov | 0.5 h | – |
| E0-2 | Write `rules/charts/NOTICE` and a separate licence note: SATS bands and colours only, own codes, EMSSA attribution, excluded from MIT | M | 5 Nov | 0.5 h | E0-1 |
| E0-3 | Email EMSSA asking for permission or confirmation of SATS use (draft below) | M | 5 Nov | 0.3 h | – |
| E0-4 | Ask Clinton for the exact submission timestamp, the format (repo, video, deck), and whether the brother can be listed as a team member | M | 5 Nov | 0.2 h | – |
| E0-5 | Agree the API contract (7 endpoints, PDF §13); B starts on fake JSON | M+B | 5 Nov | 1 h | – |
| E0-6 | CI: ruff, mypy, pytest, `next build` on every push | B | 6 Nov | 1 h | E0-1 |

**Acceptance:** the repo is public; licences are separated; the contract is written in `docs/api.md`.

---

## Epic E1: SATS rules and scoring (fixed code)

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E1-1 | Chart registry: `rules/charts/sats_adult_2012.yaml` holding the TEWS bands, colours, target times and manual page per band | M | 5 Nov | 1.5 h | E0-2 |
| E1-2 | Sign allow-list in YAML: 2 RED, 12 ORANGE, 5 YELLOW codes with short own glosses (verified list, PDF §2) | M | 5 Nov | 0.5 h | E1-1 |
| E1-3 | Chart selection by age/height (adult = over 12 y or over 150 cm). Otherwise return "no chart for this patient yet" | M | 6 Nov | 1 h | E1-1 |
| E1-4 | Pure `score(observations, chart) -> {tews, colour, points[], cited_ids[]}` | M | 6 Nov | 1.5 h | E1-1 |
| E1-5 | Plausibility limits in YAML (provisional, labelled; e.g. HR 20–250, Temp 30–43) | M | 6 Nov | 0.5 h | – |
| E1-6 | Trigger rule (code): colour rise, current ORANGE/RED sign, or nurse-reported worsening → proposal. Otherwise log only. Never downgrade | M | 6 Nov | 1 h | E1-4 |
| E1-7 | Tests: the 11 fixtures from PDF §11 (B, B2, M1→M2, Y, O, R, T, P-014, C) | M | 6 Nov | 1 h | E1-4 |
| E1-8 | Tests: band-edge grid generated from a **second, independent transcription** of the table | M | 6 Nov | 1 h | E1-4 |

**Acceptance:** `pytest tests/rules` passes; all fixture scores match the manual; there is no LLM anywhere in scoring.

---

## Epic E2: Infrastructure (one command)

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E2-1 | `docker-compose.yml`: HAPI (built-in DB), WSO2 FHIR MCP, nginx, Postgres 16, `db-init` (one-shot), FastAPI, Next.js (prod build), seed job, health checks | B | 6 Nov | 3 h | E0-5 |
| E2-2 | Two networks: `fhir_ro` (WSO2 + nginx) and `fhir_rw` (nginx + HAPI + afya-mcp). Publish **only** UI on `127.0.0.1:3000` | B | 6 Nov | 1 h | E2-1 |
| E2-3 | nginx gateway, **GET only**: raw-URI match; 403 on `;` `..` `%2e` `%2f` `$`; clear method-override headers | B | 9 Nov | 1 h | E2-2 |
| E2-4 | WSO2 config: `FHIR_SERVER_DISABLE_AUTHORIZATION=True` inside the private network, FHIRPath response trimming | B | 9 Nov | 1 h | E2-2 |
| E2-5 | Host Ollama: `qwen3:8b` + `qwen3:4b-instruct`, bound to the Docker bridge (not 0.0.0.0); `OLLAMA_BASE_URL`. Optional `--profile ollama` CPU container | M | 6 Nov | 0.5 h | – |
| E2-6 | Seed job: 20 synthetic patients loaded into HAPI | B | 8 Nov | 1 h | E5-1 |
| E2-7 | Clean-machine test: fresh clone, then `docker compose up`, then a working demo | B | 14 Nov | 1 h | all |

**Acceptance:** one command starts everything. `docker compose exec wso2 curl hapi:8080` fails. No port other than 3000 is reachable.

---

## Epic E3: PostgreSQL data layer

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E3-1 | `db-init` runs Appendix A DDL as `afya_owner`: schemas `afya` and `lg`, tables, CHECKs, grants | M | 9 Nov | 1.5 h | E2-1 |
| E3-2 | Roles: `afya_app` LOGIN, NOSUPERUSER, not a member of owner, no CREATE. Owner and superuser passwords only in db-init | M | 9 Nov | 0.5 h | E3-1 |
| E3-3 | Audit triggers that block UPDATE, DELETE and TRUNCATE. `actor` is an FK to users (incl. `agent`, `system`); `auth = demo_switcher` | M | 9 Nov | 0.5 h | E3-1 |
| E3-4 | `PostgresSaver.setup()` as owner in the `lg` schema; app gets SELECT, INSERT, UPDATE and DELETE on `lg` | M | 9 Nov | 0.5 h | E3-1 |
| E3-5 | Repository functions: approve (role check → 403, then single-use UPDATE → 409), claim (not expired, latest reading, proposal approved), mark done, startup sweep | M | 11 Nov | 2 h | E3-1 |
| E3-6 | Dedup: `UNIQUE(visit_id, trigger, evidence_hash)`; hash = sorted obs IDs + sign codes + rules version; `INSERT … ON CONFLICT DO NOTHING` | M | 12 Nov | 1 h | E3-1 |

**Acceptance:** a test logged in as `afya_app` sees UPDATE, DELETE and TRUNCATE on `audit_log` refused; double approve returns 409; manager approve returns 403.

---

## Epic E4: afya-mcp server (6 tools)

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E4-1 | FastMCP server skeleton with two mounts: **read** (model-facing) and **act** (executor only) | M | 9 Nov | 1 h | – |
| E4-2 | `record_vitals(observations[LOINC], idempotency_key)` makes a conditional-create Observation and updates `visits.latest_obs_id` | M | 9 Nov | 2 h | E3-1 |
| E4-3 | `compute_tews(observation_id)` reads the values itself, picks the chart, returns score, colour, chart_id and cited IDs | M | 9 Nov | 1 h | E1-4 |
| E4-4 | `check_deterioration(patient)` returns change, trigger type and cited records | M | 10 Nov | 1.5 h | E4-3 |
| E4-5 | `get_queue_state()` returns waits vs SATS targets, overdue re-checks (site intervals), unread proposals | M | 10 Nov | 1.5 h | E3-1 |
| E4-6 | `raise_recheck_flag(command_id)` uses the executor registry keyed by `action_type`: claim, then conditional-create Flag + Encounter priority, then mark done + audit | M | 11 Nov | 2.5 h | E3-5 |
| E4-7 | `notify_staff(kind, proposal_id)`: fixed text, nothing clinical, audited | M | 12 Nov | 1 h | E3-1 |
| E4-8 | Audit every tool call: inputs, outputs, time, actor, latency | M | 9–12 Nov | incl. | E3-3 |

**Acceptance:** each tool has unit tests. A forged `raise_recheck_flag` call from the read mount is refused. A retried write never duplicates.

---

## Epic E5: Agent (LangGraph)

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E5-1 | Write 20 synthetic patients (8 positive, 12 hard negatives; PDF §11 mix) with invented multilingual complaints. Split: 6 tuning, 14 held out | M | 7–8 Nov | 3 h | E1-7 |
| E5-2 | Event-run graph, one thread per vitals event (`visit:obs_id`): validate → record → score → deteriorate → map_signs → trigger → investigate → proposal + `interrupt()` → executor | M | 10 Nov | 3 h | E4-* |
| E5-3 | **map_signs** (Call A): JSON schema, enum codes, current/other, quote ≤15 words; code checks literal quote, status and allow-list; drops logged | M | 10 Nov | 2 h | E1-2 |
| E5-4 | **investigate** (Call B): at most 4 read-only tool calls (WSO2 search/read + 3 afya reads), then `submit_decision`. ToolNode built from the **same** filtered list. Only sign codes, never quotes. FHIR trimmed to code/value/time/id | M | 11 Nov | 3 h | E5-2 |
| E5-5 | Urgency rule: the model can only add (re-measure, extra trigger, missing value). Code always creates a proposal on a trigger | M | 11 Nov | 0.5 h | E5-4 |
| E5-6 | Rationale filter: prompt rule + denylist (sepsis, infection, diagnos*, antibiotic, mg, …). Failing text is replaced by a code-built sentence and logged | M | 11 Nov | 1 h | E5-4 |
| E5-7 | Watch loop (every 1 min; 30 s demo): vitals-due reminders, unread ORANGE after 5 min and RED after 1 min → `notify_staff`. RED/ORANGE notify immediately at creation | M | 12 Nov | 2 h | E4-7 |
| E5-8 | Supersession: newer vitals mark the old proposal superseded; one never reviewed stays visible as "not reviewed" | M | 12 Nov | 1 h | E5-2 |
| E5-9 | Model settings: `think:false`, `num_ctx` 8192, `num_predict` 384, temperature 0 / 0.2, timeouts 60 s/call and 240 s/run, 1 retry on bad JSON, circuit breaker, warm-up call, logged seed | M | 10 Nov | 1 h | E2-5 |
| E5-10 | Model-down fallback: score + trigger + proposal still work; card says "no model" | M | 12 Nov | 0.5 h | E5-2 |
| E5-11 | OpenRouter client: `ALLOW_REMOTE_MODEL=false` by default; refuses non-synthetic input; pinned provider; logs `usage.cost` | M | 13 Nov | 1 h | E5-9 |

**Acceptance:** P-014 runs end to end on local Qwen3 8B in under about 40 s on the RTX 3050. No write tool is ever offered to the model.

---

## Epic E6: API (FastAPI)

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E6-1 | Endpoints: `/login-as`, `/me`, `/queue`, `/vitals`, `/proposals?status=pending`, `/proposals/{id}/approve`, `/proposals/{id}/reject`, `/audit` | M | 9–11 Nov | 3 h | E0-5 |
| E6-2 | Demo sign-in behind `DEMO_MODE=1`: signed session cookie (SameSite=Strict); user taken from the session, never the body | M | 9 Nov | 1 h | E6-1 |
| E6-3 | Approve body carries colour, signs kept and override reason. One transaction writes decision + audit + command, then resumes the graph | M | 11 Nov | 1.5 h | E3-5 |
| E6-4 | Startup sweep resumes approved commands that are not done | M | 12 Nov | 0.5 h | E3-5 |

---

## Epic E7: Nurse UI (Next.js)

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E7-1 | Waiting room: confirmed colour chips, minutes waited, flags, notices (polling every 3 s) | B | 5–6 Nov | 3 h | E0-5 |
| E7-2 | Vitals entry form (coded fields + complaint) | B | 6 Nov | 2 h | E0-5 |
| E7-3 | Approval card: proposed colour, cited records, sign tickboxes with the **original complaint span** (plain text, never `dangerouslySetInnerHTML`), colour override + reason, approve/reject | B | 7–8 Nov | 4 h | E0-5 |
| E7-4 | Notices: re-measure, "no chart for this patient", "not reviewed", "complaint contains instruction-like text", clinician reminders | B | 10 Nov | 2 h | E7-1 |
| E7-5 | Audit viewer with per-run traces (server, tool, args, latency, tokens, $). Manager can read it | B | 11 Nov | 3 h | E6-1 |
| E7-6 | "Sign in as…" switcher (nurse, clinician, manager) with a visible DEMO badge | B | 9 Nov | 1 h | E6-2 |
| E7-7 | Wire to the real API; remove fake JSON | B | 11–12 Nov | 2 h | E6-1 |

**Acceptance:** the whole P-014 flow works by clicking only, and nothing changes colour before approval.

---

## Epic E8: Evaluation (EVALS.md)

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E8-1 | Harness `make eval`: runs groups A/B/C, writes raw JSONL to `evals/runs/`, rebuilds the tables | M | 9 Nov | 3 h | E5-2 |
| E8-2 | Group A (fixed code, once): the 17+ cases from PDF §11 group A, incl. gateway bypasses, WSO2→HAPI blocked, forged write tool, audit immutability | M+B | 12 Nov | 3 h | E2-3, E3-* |
| E8-3 | Group B (model-dependent): 20 patients × 5 runs × 2 models, k/n with Wilson 95% interval; negation, Swahili, injections (complaint, FHIR note, Swahili mix) | M | 13 Nov | 2 h + run time | E5-* |
| E8-4 | Group C: rules-only baseline on the same 20 patients (sensitivity, false alerts per visit) | M | 13 Nov | 0.5 h | E8-3 |
| E8-5 | Metrics: outcome, 0 ungated actions, 0 diagnosis/treatment words, citation validity, sign precision/recall, tool-order constraints, disagreeing runs, tokens/latency median and p95, cost | M | 13 Nov | 1 h | E8-1 |
| E8-6 | Write EVALS.md: template in PDF §11, one real unfixed failure with trace, hypothesis and next step; tuning vs held-out split disclosed | M | 13 Nov | 1.5 h | E8-3 |
| E8-7 | Grep the committed logs for secrets (`sk-or-`, headers) before pushing | M | 13 Nov | 0.2 h | E8-1 |

**Rule:** only report runs that actually happened. Freeze code before the final held-out run.

---

## Epic E9: Field fit (nurse interview)

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E9-1 | Prepare interview questions: re-check intervals, alert fatigue, what a "second look" card needs, local language terms | M | 6 Nov | 0.5 h | – |
| E9-2 | Interview a nurse who does outpatient triage. Record verbal consent (purpose, public repo, named or role only) | M | 7–8 Nov | 1.5 h | E9-1 |
| E9-3 | `FIELD_NOTES.md`: consent line, dated quotes she has reviewed, no patient identifiers, **two design changes** caused | M | 8 Nov | 1 h | E9-2 |
| E9-4 | Put her re-check intervals and plausibility limits into YAML, marked `source: site rule (FIELD_NOTES)` | M | 9 Nov | 0.5 h | E9-3 |

---

## Epic E10: Documentation and submission

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E10-1 | README: one-command run, hardware note (16 GB+, GPU optional), honest gaps (demo sign-in, adult chart only, local FHIR unauthenticated), "path to a pilot" paragraph, licence split | B | 13 Nov | 2 h | – |
| E10-2 | One-page `ARCHITECTURE.md`: agent shape, MCP servers built vs borrowed and why, Postgres-to-FHIR consistency, "append-only for the app role" | M | 13 Nov | 1.5 h | – |
| E10-3 | 300-word description: what it does, sub-theme, facility and workflow served | B | 13 Nov | 0.5 h | – |
| E10-4 | Demo video under 3 min, unedited, tool calls on screen: P-014 run, nurse confirms, one recovery (HR 400), watch-loop reminder. Upload to YouTube/Vimeo | B | 14 Nov | 2 h | E2-7 |
| E10-5 | Pitch deck (5–7 slides) + workflow GIF | B | 14 Nov | 2 h | – |
| E10-6 | Tag the submitted commit; **no commits after the deadline** | M | 16 Nov | 0.1 h | all |

---

## Epic E11: Live review readiness

| ID | Story | Owner | Day | Est. | Depends |
|---|---|---|---|---|---|
| E11-1 | Rehearse "add the child chart" (new YAML + selection) in **15 min** | M | 14 Nov | 1 h | E1-3 |
| E11-2 | Rehearse "add SpO2" and "change the reminder timer" | M | 14 Nov | 0.5 h | E4-2, E5-7 |
| E11-3 | Rehearse "add referral routing" (new `action_type` + executor + tool behind the gate) | M | 15 Nov | 1 h | E4-6 |
| E11-4 | 10-minute code walkthrough script: graph, tools, gates, SQL claim, evals | M | 15 Nov | 1 h | – |

---

## Day-by-day board

| Day | Mahdi | Brother |
|---|---|---|
| **5 Nov** | E0-1..4, E1-1, E1-2 | E0-5, E7-1 |
| **6 Nov** | E1-3..8, E2-5, E9-1 | E0-6, E2-1, E2-2, E7-2 |
| **7–8 Nov** (vaccines, light) | E9-2, E9-3, E5-1 | E7-3, E2-6 |
| **9 Nov** | E3-1..4, E4-1..3, E6-1, E6-2, E8-1, E9-4 → **end-to-end skeleton** | E2-3, E2-4, E7-6 |
| **10 Nov** | E4-4, E4-5, E5-2, E5-3, E5-9 | E7-4 |
| **11 Nov** | E3-5, E4-6, E5-4..6, E6-3 | E7-5, E7-7 |
| **12 Nov** | E3-6, E4-7, E5-7, E5-8, E5-10, E6-4, E8-2 | E7-7, E8-2 |
| **13 Nov** | E5-11, E8-3..7, E10-2 (code freeze before final eval run) | E10-1, E10-3 |
| **14 Nov** | E11-1, E11-2 | E2-7, E10-4, E10-5 |
| **15 Nov** | Travel to Nairobi · E11-3, E11-4 | – |
| **16 Nov** | Submit · E10-6 | – |
| **17 Nov** | Jury: walkthrough + live change | – |

---

## Risks

| Risk | Mitigation |
|---|---|
| Vaccine side effects 6–8 Nov | Light tasks only on those days; the brother carries the UI |
| Qwen3 8B slow or unreliable at tool calls | Benchmark on 9 Nov; fall back to `qwen3:4b-instruct`; fixed-code fallback |
| WSO2 or HAPI setup takes longer | Time-box to 1 day; fallback is our own Postgres tables + the official `fetch` MCP server |
| Scope creep | Cuts are listed in PDF §13; nothing new after 12 Nov |
| Repo does not run on the jury's machine | Clean-machine test on 14 Nov; README states hardware needs |
| Late commit disqualifies | Freeze 14 Nov, tag the submission commit |

---

## Draft: email to EMSSA (E0-3)

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
