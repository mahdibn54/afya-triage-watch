# Nurse UI: design spec ("make the agent visible")

Goal: in 3 minutes a jury should **see** three things without explanation:
1. which patient is getting worse, and the exact readings that prove it;
2. what the agent did, step by step, across both MCP servers;
3. that nothing happened until a nurse confirmed it.

Everything below serves one of those three. Owner: brother (B), with backend support from Mahdi (M) where noted.

## Stack

Next.js (App Router, TypeScript) · Tailwind + shadcn/ui · TanStack Query (polling, retries, "last updated" state) ·
Recharts for sparklines · Framer Motion (gate stepper only) · next-intl (EN / SW / FR) ·
`openapi-typescript` to generate API types from FastAPI's OpenAPI (no hand-written types drifting from `docs/api.md`) ·
Playwright for one end-to-end test of the P-014 flow (also used to rehearse the demo).

## Visual direction

- Calm clinical UI for a busy room: high contrast, generous spacing, large touch targets (works on a cheap Android tablet).
- SATS colours are **never the only signal**: every colour also has a label and a shape (RED ■, ORANGE ▲, YELLOW ●, GREEN ○), so it works for colour-blind staff and on a washed-out screen.
- Light theme by day, dark theme for night shifts.
- One accent colour for "agent activity" (distinct from SATS colours), so agent work never looks like a triage colour.
- Numbers in tabular figures; every number links to its FHIR record ID.

## Screens and features

### Must (core of the demo)

| # | Feature | What the jury sees | Why it scores |
|---|---|---|---|
| W1 | **Waiting-room board** | Each patient is a row with a **time-to-target bar** filling towards the SATS target (10 min for ORANGE, 60 for YELLOW…), a countdown, confirmed colour chip, flags and notices. Sorted by time left, not arrival. A **wall mode** for the clinic TV. | Fit to the triage desk; the problem is visible in one glance |
| W2 | **Evidence card with SATS-band sparklines** | On the approval card, each vital (RR, HR, temperature) is a small trend line drawn **over shaded SATS score bands**. You literally see the line cross into a higher band. Each dot shows value, points and its record ID. | Defensibility: "every flag cites the readings" becomes a picture |
| W3 | **Complaint with highlighted quotes** | The patient's words with the matched phrases highlighted and linked to sign chips (e.g. "can't catch my breath" → SOB – acute, ORANGE ▲). Negated or third-party mentions shown greyed with the reason ("not current"). | Shows the LLM's exact contribution, and its limits |
| W4 | **Gate stepper** | On every proposal: Proposed → Paused for nurse → Confirmed by *Nurse A.* → Command claimed → Written to record → Audited, each step lighting up with its time. A manager's refused attempt shows as a red ✕ on step 3. | Human-in-the-loop made visible, the challenge's core rule |
| W5 | **Agent trace ("glass box")** | A timeline per run: every tool call labelled **ours** or **borrowed (WSO2)**, every model call with tokens, latency and cost, the decision and its cited IDs. A **Replay** button steps through it. | Agentic depth (30 pts) and "tool calls on screen" for the video |
| W6 | **Demo director** (DEMO_MODE only) | A small panel to load the P-014 scenario, add the next reading, and run a **simulated clock** (×1 / ×10 / ×30) so the watch-loop reminder appears in seconds, not 5 minutes. | A reliable 3-minute video and a live demo that cannot stall |

### Should (if time allows, in this order)

| # | Feature | Notes |
|---|---|---|
| W7 | **Live cost & latency badge** | Corner badge: local model, tokens this run, median latency, $0.00 local / $ if OpenRouter. |
| W8 | **Three languages** | UI labels in English, Kiswahili and French (`next-intl`). Complaints are already multilingual. Strong African relevance. |
| W9 | **Keyboard-first** | `N` new vitals, `A` approve, `R` reject, `J/K` move between patients, `?` help. Nurses with a keyboard never touch the mouse. |
| W10 | **Shift handover sheet** | One page listing open proposals, unreviewed items and patients past their target, built by code (no LLM), printable via the browser. |

### Could (parking lot unless everything above is done)

| # | Feature | Notes |
|---|---|---|
| W11 | Installable PWA + "connection lost" banner with automatic retry | Low-bandwidth clinics |
| W12 | Offline queue for vitals entry | Only if W11 is done |

## Backend support needed (Mahdi)

| Endpoint | For | Notes |
|---|---|---|
| `GET /visits/{id}/timeline` | W2 | All readings with per-input points and record IDs |
| `GET /runs/{run_id}/trace` | W5 | Ordered steps: tool/model call, server, args (trimmed), result summary, latency, tokens, cost |
| `GET /proposals/{id}/gates` | W4 | Times for each gate step, plus refused attempts |
| `POST /demo/scenario`, `POST /demo/clock` | W6 | `DEMO_MODE=1` only; clock speed applies to the watch loop and target countdowns |
| `GET /handover` | W10 | Code-built summary |

## Rules that do not change

- Quotes and model text rendered as plain text only (never `dangerouslySetInnerHTML`).
- Nothing on screen suggests a diagnosis or treatment. The UI never calls it "AI triage".
- The manager sees no approve button anywhere.
- The demo director and "sign in as…" exist only when `DEMO_MODE=1`, with a visible DEMO badge.
