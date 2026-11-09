# Nurse-session cases (fresh held-out)

Twelve new synthetic patients written for one purpose: a held-out check the system and its prompts have never seen.
They were committed, with their expected outcomes, before any run (model or UI). Colours and whether a proposal is due
come from the SATS rules engine (`evals/make_nurse_cases.py`); the warning signs in each complaint were labelled by the
author. A practising nurse is to review the labels; any change is recorded here, not made silently.

Used two ways: entered by hand through the UI as a nurse would (end-to-end), and run repeatedly with `make eval`.

## Hands-on UI session (Groq `openai/gpt-oss-120b`, one pass)

Seeded with `python -m evals.seed_nurse_session` (first reading only). Each second reading and complaint was then typed
into the Vitals dialog as Nurse A, in the browser; the suggestions were reviewed in the patient panel and the correct
ones confirmed there. Result against the labels committed beforehand: **11/12**.

| case | expected | agent | |
|---|---|---|---|
| n01 elderly BP drop | ORANGE | ORANGE (colour rise; 5 model calls, WSO2 read) | ok, confirmed |
| n02 "worst headache of my life, 10/10" | ORANGE, SEVERE_PAIN | no proposal: the sign mapper returned no sign | **missed** |
| n03 fainted yesterday, fine now | none | none | ok |
| n04 ORANGE improving | none | none | ok |
| n05 one-sided numbness | ORANGE, FOCAL_NEURO_ACUTE | same | ok, confirmed |
| n06 French, vomited blood | ORANGE, VOMITING_FRESH_BLOOD | same | ok, confirmed |
| n07 pregnant, belly pain | ORANGE, PREGNANCY_ABDO_PAIN | same | ok, confirmed |
| n08 too many sleeping tablets | ORANGE, POISONING_OVERDOSE | same | ok, confirmed |
| n09 cough, negated chest pain and breathlessness | none | none | ok |
| n10 responds to voice only | ORANGE | ORANGE, LOC_REDUCED_CONFUSED | ok, confirmed |
| n11 bleeding stopped by bandage | none | none | ok |
| n12 Swahili, severe headache | ORANGE, SEVERE_PAIN | same | ok, confirmed |

The miss is a false negative (the riskier direction): the patient stays at the nurse's confirmed GREEN and is not
flagged. The nurse can still raise it with "patient feels worse" in the Vitals dialog. Any prompt change made because
of this case is tuned on it, so after such a change n02 no longer counts as held-out.
