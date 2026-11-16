# Field notes: nurse interview (E9)

Interviewed on Day 10: a practising triage nurse, described by role only. Verbal consent to a public summary was given;
she reviewed every answer below. No patient was described in a way that could identify them. No contact details here.

## How the interview was run

We prepared one proposed answer to each of 18 questions (`docs/interview-guide.md`), researched from the SATS training
manual (EMSSA 2012), EMSSA's SATS implementation guideline (EM014), Australasian triage guidance and published studies
on alert fatigue, family-reported confusion and pulse oximetry. She judged each one: yes, partly or no.
**She agreed with all 18.** The answers are summarised below as she accepted them.

## What she confirmed

- **The gap (Q1-3).** One triage nurse at the desk sees 50 or more patients a shift. Triage is on paper or by
  judgement, not a validated scale in a computer. Nobody re-checks waiting patients on a schedule: deterioration is
  noticed when the family comes to the desk or when the patient's name is called. This is the problem Afya addresses.
- **Re-checks (Q4).** RED never waits. ORANGE is re-checked at least every 10 minutes, YELLOW every 30, GREEN every
  2 hours: no later than the SATS target for ORANGE, halfway to it for YELLOW and GREEN.
- **Who is told (Q5-6).** An overdue re-check goes to the nurse in charge; a move to a more urgent colour goes to the
  senior doctor at once. Unanswered proposals: remind after 1 minute (RED) and 5 minutes (ORANGE), as today.
- **The card (Q7-8).** In this order: colour now and proposed, the reading or words that caused it with the time, the
  wait against the target, one button. More than about one alert an hour per nurse is too many; an alert must never
  repeat for the same patient.
- **A YELLOW sign on a GREEN patient (Q9).** It should raise the patient to YELLOW, as the SATS manual says ("an urgent
  sign … immediately triaged yellow"). Afya only notes it today.
- **Lower colours (Q10).** The system never suggests one; only a senior nurse or doctor lowers a colour.
- **The family says "confused" (Q11).** Believe the family: treat as confused (ORANGE), glucose test, hand to a senior.
  This is our unfixed eval failure `s07`.
- **Numbers (Q12-13).** The plausibility limits are right; SpO2 below 70% must always be re-measured, and a confirmed
  extreme value must be saved, never discarded. Pain follows the patient's words (severe = unbearable, worst ever;
  moderate = intense but bearable); when a number is given, 7-10 is severe and 4-6 moderate.
- **Words and cases (Q14-15).** The French phrases and the expected answers for cases n02, n06 and s07 are right.
- **Switching it off (Q16-17).** False or repeated alerts, extra typing and unreliable equipment would make her switch
  it off; the first improvement would be vital signs taken automatically from the monitor.

## Design change 1: re-check intervals

Before: placeholders RED 5, ORANGE 15, YELLOW 30, GREEN 60. Our ORANGE value was longer than ORANGE's own 10-minute
target. After: ORANGE 10, GREEN 120 (RED and YELLOW unchanged), in `rules/site.yaml`, marked
`source: site rule (FIELD_NOTES, Day 10)`. Config only; the queue test was updated to the new values.

## Design change 2: pain bands

Before: our working assumption was 8-10 severe, 5-7 moderate. After: the patient's words decide, as in SATS, and a
stated number uses 7-10 severe and 4-6 moderate (`rules/charts/NOTICE.md`, `evals/cases/nurse_session/README.md`). The
sign-mapper prompt already reads severity from the patient's words, so no code changed; no eval label changed either
(the only numeric case, `s10`, "6 out of 10", is moderate under both bands).

## Agreed but not changed before submission, and why

Each of these changes what the agent proposes, so it would make our logged evals (`EVALS.md`) out of date two days
before submission. They are the next work, each followed by a new eval run:

1. **Q9:** a YELLOW sign raises a GREEN patient to YELLOW (trigger rule; flips the expected label of five cases:
   `n11`, `s08`, `s09`, `s10`, `s11`).
2. **Q11 / s07:** words reported by a relative count as the patient's sign (the fix already written in `EVALS.md`
   section 4).
3. **Q10:** only a senior nurse or doctor may lower a colour (role check on the override).
4. **Q12:** SpO2 below 70% always asks for a re-measure, and a confirmed extreme value is saved instead of refused.
