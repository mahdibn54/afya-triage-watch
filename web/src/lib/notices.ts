import type { NoticeCode } from "@/api/contract";

// UI wording for every notice code (docs/api.md section 6). Plain words, from the say/avoid table:
// we flag, remind and ask; we never diagnose, predict or move anyone.
export const NOTICE: Record<NoticeCode, { title: string; body: string; tone: "info" | "warn" | "agent" | "muted"; short: string }> = {
  remeasure: {
    short: "Re-measure",
    title: "Please re-measure",
    body: "A value was outside the plausible range, so nothing was saved or scored. Measure again and re-enter.",
    tone: "warn",
  },
  no_chart: {
    short: "No chart",
    title: "No chart for this patient yet",
    body: "This patient is outside the adult SATS chart, so no score or target is shown. Triage by hand.",
    tone: "muted",
  },
  not_reviewed: {
    short: "Not reviewed",
    title: "A suggestion was not reviewed",
    body: "A newer reading replaced a second-look suggestion before anyone read it. Glance at it and mark it as seen.",
    tone: "agent",
  },
  instruction_like_text: {
    short: "Odd text",
    title: "The complaint contains instruction-like text",
    body: "Part of the complaint reads like an instruction. It was treated as the patient's words only, and nothing in it was followed.",
    tone: "warn",
  },
  vitals_due: {
    short: "Vitals due",
    title: "Vitals are due",
    body: "The site re-check interval has passed. Take a new set of vitals when you can.",
    tone: "warn",
  },
  clinician_reminded: {
    short: "Clinician reminded",
    title: "Clinician on duty reminded",
    body: "A second-look suggestion has waited a while, so the clinician on duty was reminded.",
    tone: "agent",
  },
  model_unavailable: {
    short: "Language model offline",
    title: "The language model is offline",
    body: "Scores, colours and second-look suggestions keep working from the fixed SATS rules. Complaint phrases are not matched until it is back.",
    tone: "info",
  },
  fhir_unavailable: {
    short: "Records offline",
    title: "The patient record server can't be reached",
    body: "The waiting room can't be loaded from the records right now. Keep triaging by hand; the board refreshes when the connection is back.",
    tone: "warn",
  },
  agent_failed: {
    short: "Check not finished",
    title: "The watch agent could not finish a check",
    body: "A reading was saved, but the watch agent could not finish checking it. Review the patient yourself and record a new reading to start a fresh check.",
    tone: "warn",
  },
  command_abandoned: {
    short: "Flag not recorded",
    title: "The confirmed second look was not recorded",
    body: "Your confirmation expired or the record could not be updated. Review the patient and record a new reading for a fresh suggestion to confirm.",
    tone: "warn",
  },
  data_incomplete: {
    short: "Data missing",
    title: "Some visit data is missing",
    body: "A visit lacks data the board needs (patient, colour or arrival time), so it may not be shown correctly. Check it in the record.",
    tone: "muted",
  },
};

/** Wording for a code; an unknown code (a newer API) gets a neutral notice instead of breaking the page. */
export function noticeText(code: string): (typeof NOTICE)[NoticeCode] {
  return (
    NOTICE[code as NoticeCode] ?? {
      short: "Notice",
      title: "Notice",
      body: `The server sent a notice this screen does not know yet (${code}).`,
      tone: "muted",
    }
  );
}
