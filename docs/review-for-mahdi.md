# Review notes for M (from B, Day 8)

Found while reviewing M's work against the code, the backlog and the live compose stack. Nothing here breaks a safety
invariant: scores and triggers stay in fixed code, the model can only add urgency, it gets no free text and no write
tool, and nothing changes before a nurse confirms. These are the items left for M. When one becomes a story, it goes
into `Afya_Tasks_BMAD.md` (the backlog stays the only task list) and the line here can be deleted.

## 1. `model_unavailable` notices pile up

`api/afya_api/agent.py`, `Agent._model_down`: called every time the circuit breaker opens. While Ollama is down the
breaker re-opens after each 5-minute cooldown, and every time a new `model_unavailable` notification is inserted
without checking for an open one. On the compose stack: 34 open, none acknowledged.

The board shows each one as a banner (B will group them by code in E7-10), but the backend should keep at most one
open: skip the insert when an unacknowledged `model_unavailable` exists (in `_model_down`, or in `notify_staff` for
that kind).

## 2. `GET /proposals` has no visit filter and no limit

`api/afya_api/routes_proposals.py` `get_proposals` → `workflow.list_proposals`: returns every proposal with its full
payload. The visit panel polls `?status=all` every 3 s and filters by visit in the browser; the board polls
`?status=pending`. Measured on the compose stack: `all` 476 KB, `pending` 308 KB per request (about 0.5 s each).

Proposal: an optional `visit_id` query parameter (and a sane `limit`, newest first for `all`). B then updates
`docs/api.md` section 6 and makes the visit panel use `?visit_id=`.

## 3. Clinician reminders stay open after the decision

`clinician_reminder` notifications are never closed when their proposal is approved or rejected, so the patient keeps
the "Clinician reminded" chip until someone dismisses it. On the stack: 549 open (5 of them on approved proposals,
10 on superseded ones; most of the rest are test leftovers, see item 6). Close them (`acknowledged_at`) in the
approve/reject transaction, or have `open_notifications` skip reminders whose proposal is no longer pending.

## 4. `GET /proposals` and the queue are polluted by leftover test data

Not a code bug. The API tests write to whatever `DATABASE_URL` points at, and on Day 8 they ran against the compose
database: 283 pending proposals and 578 visits whose Encounters do not exist in HAPI. The startup sweep keeps retrying
their commands (`FhirNotFound` in `audit_log`) and the watch loop reminds staff about them. This inflates items 1 to 3.

Proposal: agree a time to recreate the Postgres volume before the demo recording (`docker compose down -v`, which wipes
all data), and run the tests against a separate database from now on (for example a `postgres-test` service or a
second database on the same server).

## 5. Backlog entries that no longer match the code

- **Decisions log:** "Model choice decided by a Day 5 benchmark: qwen3:8b vs qwen3:30b-a3b". That benchmark was not
  run (E5-9 notes, "by decision"); the evals compare qwen3:8b with qwen3:4b-instruct. Replace the entry with what was
  decided and why.
- **E6-1b Notes:** "it raises 501 until E6-2 replaces its body". E6-2 is done; it answers 401.
- **E6-6 Notes:** "Until E5 exists the second reading does not produce a proposal". E5 is done.
- **E0-6 Notes:** "52 existing errors in `mcp/afya_mcp`". It is 59 now (item 6).
- **E2-5** (B's story) is still `[ ]` but M did the binding (E5-9 notes: systemd override
  `OLLAMA_HOST=172.17.0.1:11434`, the api container reaches the model). B will close it, with the deviation that
  qwen3:30b-a3b was not pulled, unless M disagrees.

## 6. mypy (still open in E0-6)

`mypy afya_mcp`: 59 errors (3 arg-type, 35 call-overload, 9 index, 3 operator, 8 return-value, 1 union-attr).
`mypy afya_api`: 43. Almost all are psycopg rows typed as tuples where the code uses `dict_row`, which is typing noise.
Typing the connections as `psycopg.Connection[DictRow]` removes most of them. Then either make mypy fail the CI or record
in E0-6 that it stays advisory.

One is a real risk: `api/afya_api/mcp_client.py:60`, `res.content[0].text`. A tool result that is not `TextContent`
raises `AttributeError`, which `helpers.tool_error` turns into a vague 503. Check `isinstance(..., TextContent)` and
raise `ToolFailed` with a clear text.
