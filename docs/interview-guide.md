# Nurse interview guide (E9-1)

For one conversation of about 45 minutes with a nurse who triages in an outpatient or emergency department. Each
question names what its answer changes in the repo. Notes go into `FIELD_NOTES.md` (E9-3); numbers she gives go into
`rules/site.yaml` and `rules/plausibility.yaml` with `source: site rule (FIELD_NOTES)` (E9-4).

## Before starting: consent (E9-2)

Say, and note her answer:

- "We are building a research prototype that watches the waiting room and suggests a second look. It never decides."
- "Your answers will be summarised in a public code repository. Do you want to be named, or described by role only
  (for example 'triage nurse, public hospital outpatient department')?"
- "Please do not tell me anything that could identify a patient. If you describe a case, I will paraphrase it."

## 1. Her work today (5 min)

1. Where do you triage, how many patients a shift, how many nurses at the desk?
2. Do you use SATS (or another scale) every day? On paper, a form, a computer?
3. After triage, who watches the people waiting? How would you notice that someone got worse?

## 2. Re-checks (10 min) → `rules/site.yaml` `recheck_minutes`

Show our placeholders: RED 5 min, ORANGE 15, YELLOW 30, GREEN 60.

4. How often should a waiting patient's vitals be re-taken for each colour? How often does it really happen?
5. When a re-check is overdue, who should be told: the triage nurse, the nurse in charge, the doctor?
6. A proposal nobody answers: after how many minutes should the doctor on duty be reminded (we use RED 1, ORANGE 5)?

## 3. The second-look card (10 min) → the approval card, alert rules

Show the screen with P-014 (YELLOW to ORANGE, the readings cited).

7. What must this card show for you to trust it in five seconds? What is missing? What is noise?
8. Alert fatigue: how many alerts an hour before you start ignoring them?
9. **A YELLOW warning sign (for example vomiting) on a patient triaged GREEN: alert, or only note it?** Today we
   only note it.
10. Should the system ever suggest a lower colour? (Today it never does.)
11. A relative says "my father is confused" but you recorded him as alert. Whom do you believe, and should the agent
    flag it? (Our unfixed failure, case s07.)

## 4. Numbers and words (10 min) → `rules/plausibility.yaml`, the sign prompts

12. Values you would never accept without re-measuring (our limits: RR 3-70, HR 20-250, SBP 40-300, temp 30-43,
    SpO2 50-100)?
13. Pain: is 8-10 severe and 5-7 moderate as in our chart? Do patients give a number?
14. How do patients describe these in Swahili, French, Arabic or sheng: coughing blood, vomiting blood, fitting,
    confusion, belly pain, "the worst headache of my life"? (Check our cases s03, s04, s09, s13, n06, n12.)
15. Read three of our nurse-session cases aloud: does this happen at your desk? What is unrealistic?

## 5. Closing (5 min)

16. If this existed at your desk tomorrow, what would make you switch it off?
17. One thing you would change first.
18. May we contact you again with a short follow-up question?

Afterwards: write `FIELD_NOTES.md` the same day (what she said, paraphrased; what changed in the repo and why; what
we did not change and why).
