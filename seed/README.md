# Synthetic waiting-room seed (E2-6)

Start the stack using the root README, then run:

```sh
docker compose --profile seed run --build --rm seed
```

The explicit one-shot job waits for HAPI and database initialization. It requires
`DEMO_MODE=1` and `DATA_CLASSIFICATION=synthetic`; it uses the application database
role and private FHIR write network, without publishing any ports or adding model tools.

It loads the 20 E5-1 cases as `SYN-b01-…` through `SYN-b20-…` labels, with one
Patient, one Encounter and the **first reading only** per case. This is the waiting-room
starting state, not a replay or evaluation.

It also loads four demo-video patients from the eval cases (`SYN-n02-…`, `SYN-m05-…`, `SYN-m16-…`, `SYN-n06-…`),
again first reading only, with normal vitals and no complaint. For the demo, the nurse records a new reading with the
case's complaint typed live (text in each case file under `evals/cases/`): n02 a complaint-only sign, m05 and m16 no
flag expected (someone else's symptom, a denied sign), n06 the French complaint Qwen missed in 3 of 3 runs. Later readings (including HR 400 and
Fahrenheit inputs), FHIR-note injection payloads, and expected evaluation labels are
not imported. Complaints remain in Postgres through the existing recording service.
No model calls, proposals, approvals or Flags are created by this job.

The fixture's initial confirmed colour represents an existing synthetic staff decision;
the first-visit case stays unconfirmed. Mahdi's label/translation review remains pending
under E5-1; loading these invented cases does not imply that review is complete.

Rerunning reuses identifiers (`urn:afya:seed:v1` for visits, visit-scoped
`seed-v1-baseline` for readings), repairs partial FHIR/Postgres runs and retains the
original arrival times. It never resets a confirmed colour, finishes another visit,
reopens a closed visit or replaces a newer reading. Concurrent job invocations are
serialized with a Postgres advisory lock. Intent and result audit rows are appended
on each attempt, so retries add audit records but do not duplicate clinical resources.
An error exits nonzero; rerun the same command after fixing the cause.

The output contains case, patient, visit and baseline Observation IDs. Open the nurse
board to see the seeded labels. Existing P-014 demo visits remain separate. To start
over, use a separate disposable Compose project; this job offers no destructive reset.

Verification: `python -m pytest evals/tests/test_seed.py -q`.

With the real UI stack running and seeded, run desktop Chromium and iPhone browser
emulation from `web/`: `npx playwright test --config playwright.seed.config.ts`.
The checks cover all 20 labels, initial confirmation states, keyboard focus, opening
a patient panel, horizontal overflow and browser errors. Board and patient-panel
screenshots are saved in `.playwright-mcp/seed/browser/` and uploaded by CI.
