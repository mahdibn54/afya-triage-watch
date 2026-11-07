# Database notes

Schema: `db/schema.sql`, applied by `db/init.sh` (service `db-init`) as `afya_owner`, in one transaction (`psql -1`), to
two databases on the same server: `afya` (the stack's data) and `afya_test` (automated tests only).

## Existing volumes (migration)
Everything in `schema.sql` is idempotent (`IF NOT EXISTS`, `OR REPLACE`, drop-then-create inside the one transaction), so a
volume created by an older version is migrated in place, no data lost and no trigger missing while the app runs:

    docker compose run --rm db-init      # then: docker compose run --rm lg-init   (checkpoint tables of afya_test)

`afya.schema_version` says what was applied (2 = E12-2). Commands the old version left open and unrunnable (expired,
stale, or out of attempts) are marked abandoned by the next startup sweep, with an audit row each.

## Abandoned commands (E12-2)
An approved command that can never run is abandoned, not retried for ever: `expired` (never claimed, older than its
one-hour TTL), `stale` (never claimed, newer vitals arrived) or `attempts` (claimed, not done, five attempts used). The
startup sweep sets `commands.abandoned_at` and `abandon_reason`, writes a `command_abandoned` audit row (actor `system`)
and, for expired or failed ones approved less than a day ago, one open `command_abandoned` notice per visit. Nothing was
written to FHIR. To re-open the work the nurse records a new reading: it gets a fresh proposal, which she approves (the
old proposal is single-use and its dedup key stays taken).

## Tests use their own database
`pytest` in `mcp/` and `api/` only uses `TEST_DATABASE_URL` (database `afya_test`), or a `DATABASE_URL` that is not the
stack's `afya` (`mcp/tests/dbselect.py`); otherwise the DB tests skip. `eval "$(sh evals/stack_env.sh)"` exports it. The
app role cannot delete, so test rows stay in `afya_test`; their ids start with `synthetic-test-`. `scripts/smoke.sh`
runs against the stack and tags what it leaves: visit ids `synthetic-smoke-...`, patient labels `SMOKE-...`, keys `smoke-...`.

## Reset (destroys data: Mahdi decides when)
- Empty only the test database:
  `docker compose exec postgres psql -U "$PG_SUPERUSER" -d postgres -c 'DROP DATABASE afya_test'`, then
  `docker compose run --rm db-init && docker compose run --rm lg-init` (recreates it).
- Empty everything (stack data, HAPI data, checkpoints): `docker compose down -v`, then `docker compose up --build`.
  The `-v` removes ALL named volumes: Postgres and HAPI. Do it before recording the demo, never while someone is using it.

## Design notes
No connection pool by design (a short-lived connection per afya-mcp call, one per api request; see `afya_mcp/db.py`).
The audit log is append-only for the app role but has no hash chain: a database administrator can still rewrite it.
