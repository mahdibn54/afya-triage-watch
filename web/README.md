# web/ — nurse UI (Next.js)

Owner: brother. Backlog: epic E7 in `docs/Afya_Tasks_BMAD.md`. API contract: `docs/api.md`.

To do first: `npx create-next-app@latest .` (TypeScript, App Router), then a production `Dockerfile`
listening on port 3000 that proxies `/api/*` to `API_INTERNAL_URL`. Then enable it with
`docker compose --profile web up --build`.

Rules: poll every 3 s; render complaint quotes as plain text; show a visible DEMO badge next to "sign in as…".
