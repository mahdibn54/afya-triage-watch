# web/ — nurse UI (Next.js)

Owner: brother (B). Backlog: epic E7 in `docs/Afya_Tasks_BMAD.md`. Design spec: `docs/web-design.md`.
API contract: `docs/api.md`.

Stack: Next.js 16 (App Router, TypeScript) · Tailwind 4 + shadcn/ui (Base UI) · TanStack Query (3 s polling).

## Run

The UI talks to the real API only (E7-10 removed the fake). Run it in the compose stack:

```bash
docker compose --profile web up -d --build    # UI on http://127.0.0.1:3000, the API stays on the private network
```

`npm run build` makes the production build (standalone server); `web/Dockerfile` is what compose runs.

| Env var | Where | Meaning |
|---|---|---|
| `API_INTERNAL_URL` | server | FastAPI base URL (`http://api:8080` in compose). `/api/*` is proxied there at request time, prefix stripped, cookies passed both ways. |

Demo mode, the "sign in as…" switcher and the demo director come from the API (`GET /me` → `demo`), not from a UI
variable.

## End-to-end test (E7-11)

```bash
npx playwright install chromium          # once
npm run test:e2e                         # the P-014 flow against the running stack (PW_BASE_URL, default http://127.0.0.1:3000)
```

It loads the P-014 demo scenario, so it needs `DEMO_MODE=1`. It passes with the language model on or off (the quote
highlights are only checked when the sign mapper ran).

## API types

`src/api/types.ts` is generated from FastAPI's `/openapi.json`; `src/api/contract.ts` only gives its schemas the
names the components use. After an API change, with the stack running:

```bash
npm run gen:api        # API_URL defaults to http://127.0.0.1:3000/api (the UI's proxy)
npm run typecheck      # every place that has to follow the change
```

## Rules

Poll every 3 s · complaint quotes are plain text (never `dangerouslySetInnerHTML`) · a visible DEMO badge next to
"sign in as…" · a manager sees no approve button · SATS colours always with a label and a shape.
