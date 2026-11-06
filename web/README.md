# web/ — nurse UI (Next.js)

Owner: brother (B). Backlog: epic E7 in `docs/Afya_Tasks_BMAD.md`. Design spec: `docs/web-design.md`.
API contract: `docs/api.md`.

Stack: Next.js 16 (App Router, TypeScript) · Tailwind 4 + shadcn/ui (Base UI) · TanStack Query (3 s polling).

## Run

```bash
cd web
npm install
npm run dev:fake        # fake API from the contract's example JSON, http://localhost:3000
npm run build           # production build (standalone server)
```

| Env var | Where | Meaning |
|---|---|---|
| `API_INTERNAL_URL` | server | FastAPI base URL. `/api/*` is proxied there at request time (prefix stripped). |
| `FAKE_API` | server | `1` serves the in-memory fake (`src/server/fake-api.ts`) instead of proxying. Until E7-10. |
| `DEMO_MODE` | server, fake only | `0` hides the "sign in as…" switcher and demo routes in the fake. |

In compose: `docker compose --profile web up --build` (UI on `127.0.0.1:3000`).

## End-to-end test (E7-11)

```bash
npx playwright install chromium          # once
npm run test:e2e                         # starts the UI on the fake API and runs the P-014 flow
PW_BASE_URL=http://localhost:3000 npm run test:e2e   # against a running stack instead
```

`FAKE_ALL_NOTICES=1` makes the fake also show `model_unavailable` and `instruction_like_text`.

## Fake JSON

`npm run fixtures` copies every `<!-- example: ... -->` block of `docs/api.md` into `src/api/fixtures/`, so the
fake always matches the contract. The fake never scores readings (scores come only from `rules.py`); it replays the
P-014 scenario from the contract examples.

## API types

`npm run gen:api` (with `API_URL`, default `http://localhost:8080`) regenerates `src/api/types.ts` from FastAPI's
`/openapi.json`. Until the E6 endpoints have response models, `src/api/contract.ts` mirrors `docs/api.md` by hand.

## Rules

Poll every 3 s · complaint quotes are plain text (never `dangerouslySetInnerHTML`) · a visible DEMO badge next to
"sign in as…" · a manager sees no approve button · SATS colours always with a label and a shape.
