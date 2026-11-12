# Ten-minute code walkthrough (E11-4)

For the live review. Order: graph → tools → gates → SQL claim → evals. Open each file at the line given; say the
sentence in bold, show the code, move on. Timings add up to 10 minutes.

## 1. The graph (2 min): `api/afya_api/agent.py`

- `agent.py:339-352`: **"One LangGraph run per saved reading, ten nodes in a fixed chain."** validate → record → score →
  deteriorate → map_signs → trigger → investigate → proposal → paused → executor. Conditional edges stop the run
  early (nothing changed, no trigger).
- `mcp/afya_mcp/rules.py:76` `score` and `:182` `evaluate_trigger`: **"Fixed code decides the score, colour and
  trigger. The model never computes them."** The chart is data: `rules/charts/sats_adult_2012.yaml`.
- `api/afya_api/signs.py:136` `check_signs`: **"The model only maps the complaint to sign codes, and code checks
  every one"**: allow-listed code, a quote that is really in the complaint, no instruction-like text.
- `agent.py:327-329` `paused`: **"LangGraph `interrupt()`: the run stops here and waits for a person."**

## 2. The tools (2 min): `mcp/afya_mcp/server.py`

- `server.py:148-172`: read mount, given to the model: `compute_tews`, `check_deterioration`, `get_queue_state`.
- `server.py:185-237`: act mount, never given to the model: `record_vitals`, `raise_recheck_flag`, `notify_staff`,
  `seed_demo_visit`. **"Each mount is a separate OAuth 2.1 resource with its own scope; the model's token only has
  `afya:read`."**
- `api/afya_api/investigate.py:364`: the investigate loop: **"The model chooses up to 4 reads, ours or the borrowed
  WSO2 FHIR `search`/`read`, then submits a decision."**
- `server.py:111` `_audited`: **"Every tool call writes its audit row before it returns. No row, no result."**

## 3. The gates (2 min): `api/afya_api/routes_proposals.py`, `mcp/afya_mcp/workflow.py`

- `routes_proposals.py:71-92` `approve`: **"403 wrong role, 409 already decided, 422 override without a reason."**
- `workflow.py:372` `approve_proposal` and `:341`: **"Role check, a single-use UPDATE, then decision, command and
  audit in one transaction. Managers can only read."**
- `api/afya_api/decision.py:185` `rationale_text`: **"The model's sentence is shown only if every number and id is
  real, it names the proposed colour and the sign; otherwise code writes it."**

## 4. The SQL claim (2 min): `mcp/afya_mcp/services.py`, `db/schema.sql`

- `services.py:536-557` `run_command`: **"A session advisory lock: two executors can never run the same command."**
  The FHIR Flag is a conditional create keyed on the command id, so a retry converges to the same Flag.
- `db/schema.sql:258-273`: **"The app's role cannot UPDATE or DELETE the audit log: INSERT and SELECT only."**

## 5. The evals (2 min): `EVALS.md`, `evals/`

- `EVALS.md` headline: **"61 of 63 cases, 3 runs each, 0 false alerts; the rules alone get 43."**
- `evals/cases/sign_coverage/`: **"Written before any run; this is where our two misses are."**
- `EVALS.md` section 4: **"s07: a relative says 'my father is confused' and the model reads it as someone else.
  Held out, so we did not tune on it; the next step is written there."**
- `evals/runner.py:173` `run_trial`: one trial drives the real stack end to end; `python -m evals tables` rebuilds
  every table from the raw logs in `evals/runs/`.

## Likely live requirements and where they go

| Ask | Where | Rehearsal |
|---|---|---|
| Add a child chart | new YAML in `rules/charts/` plus its registry entry; `select_chart` (`rules.py:44`) picks it by age | E11-1 |
| Record SpO2 / change the reminder timer | vitals form + `rules/site.yaml` (config only) | E11-2 |
| Referral routing as a new action | new `action_type`, executor in `services.py`, act tool behind the same approval | E11-3 |
| Change a re-check interval | `rules/site.yaml` `recheck_minutes`, no code | – |
