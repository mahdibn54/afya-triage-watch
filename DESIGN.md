# Afya Triage Watch design context

## Purpose and audience

Decision support for trained triage staff in public outpatient departments. The main workflow is reviewing a
waiting patient's readings and confirming or rejecting a sourced second-look suggestion. Managers can read only.
Synthetic demo identities are separate from OAuth service identities; signing in never grants the model write tools.

## Visual direction

Preserve the existing calm, high-contrast clinical interface, editorial heading typography, compact controls,
light/dark themes and generous touch targets. SATS colours always include a label and shape. Agent activity uses
the existing distinct accent. No new palette, type scale or layout system is introduced by the integration update.

## Canonical sources and owners

- Product/UI requirements and responsive behavior: `docs/web-design.md`.
- Permission, notice and session contract: `docs/api.md` and server authorization checks.
- Runtime tokens/themes: `web/src/app/globals.css`; reuse them through existing Tailwind classes.
- Notices: `web/src/lib/notices.ts` and shared `NoticeChip`/`NoticeCallout` components.
- Menus: existing shadcn/Base UI dropdown primitive, used by `UserSwitcher`.
- Async state and cache ownership: `web/src/lib/queries.ts` (TanStack Query); errors/toasts use existing providers.
- Session navigation: successful logout clears session data and returns to sign-in; failed logout keeps the session
  and shows a retry message. The API expires its HttpOnly cookie and audits the recognized actor.

## Interaction decisions

The demo director starts collapsed for nurses/clinicians and is absent for managers. Managers retain read access
to notices and audit history but have no mutation controls. Sign out lives in the existing user menu, supports
keyboard navigation and touch, and reports failure without hiding the current session. Notice text describes
what happened and the next staff action without exposing protocol implementation details.

## Verification

Exercise desktop Chromium and iPhone browser emulation, keyboard focus, permission denial, logout failure/retry,
signed-out access refusal, new notice wording, overflow and browser errors. Inspect screenshots in both sizes.
Existing application/API specifications remain the behavioral contract; this file does not create a second backlog.

## Canonical UI ownership

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | native | Existing audit-view.tsx role filter | Browser select with existing styles | Existing keyboard and browser behavior |

The static premium audit also reports five existing form-validation/textarea policy findings outside this change (vitals-dialog, approval-card and shared textarea). They remain recorded in the ignored audit artifact; this integration does not claim a clean whole-app premium audit.
