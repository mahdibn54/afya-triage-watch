# API contract (draft, E0-5)

FastAPI on `api:8080`, reached by the Next.js app through its `/api` proxy. JSON everywhere.
The signed-in user always comes from the session cookie, never from a request body.

| Method | Path | Who | Body / query | Response |
|---|---|---|---|---|
| POST | `/login-as` | anyone (DEMO_MODE=1 only) | `{ "user_id": "nurse-a" }` | `{ id, name, role }` + session cookie |
| GET | `/me` | signed in | – | `{ id, name, role, demo: true }` |
| GET | `/queue` | signed in | – | `[{ visit_id, patient_label, colour, tews, minutes_waited, target_minutes, flags[], notices[] }]` |
| POST | `/vitals` | nurse, clinician | `{ visit_id, idempotency_key, resp_rate, heart_rate, systolic_bp, temperature, spo2?, mobility, consciousness, trauma, complaint }` | `{ run_id, status: "accepted" \| "remeasure", notice? }` |
| GET | `/proposals?status=pending` | signed in | – | `[{ id, visit_id, proposed_colour, current_colour, tews_before, tews_after, cited[{obs_id, field, value, points}], signs[{code, gloss, colour, quote_span}], rationale, created_at, reviewed, superseded }]` |
| POST | `/proposals/{id}/approve` | nurse, clinician | `{ colour, signs_kept[], override_reason? }` | `200 { command_id }` · `403` wrong role · `409` already decided |
| POST | `/proposals/{id}/reject` | nurse, clinician | `{ reason }` | `200` · `403` · `409` |
| GET | `/audit?visit_id=&limit=` | signed in (manager: read only) | – | `[{ at, kind, actor, auth, run_id, payload }]` |

Notices shown in the UI: `remeasure`, `no_chart`, `not_reviewed`, `instruction_like_text`, `vitals_due`,
`clinician_reminded`, `model_unavailable`.

Quotes are rendered as plain text (never `dangerouslySetInnerHTML`). `quote_span` is `{ start, end }` into the
original complaint, which the UI slices itself.
