# Nurse-session cases (fresh held-out)

Twelve new synthetic patients written for one purpose: a held-out check the system and its prompts have never seen.
They were committed, with their expected outcomes, before any run (model or UI). Colours and whether a proposal is due
come from the SATS rules engine (`evals/make_nurse_cases.py`); the warning signs in each complaint were labelled by the
author. A practising nurse is to review the labels; any change is recorded here, not made silently.

Used two ways: entered by hand through the UI as a nurse would (end-to-end), and run repeatedly with `make eval`.
