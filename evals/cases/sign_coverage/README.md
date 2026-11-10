# Sign coverage cases (pre-registered)

13 synthetic cases, written and committed **before any run**. Each one targets a SATS warning sign that no earlier
case expected the model to find (`s01`-`s11`), plus two neighbours: a YELLOW sign on a patient already confirmed
YELLOW (`s12`, no proposal) and negated convulsions in code-switched Swahili (`s13`, must find nothing).

- Expected colours come from the rules engine (`rules.score` and `rules.evaluate_trigger`); signs and forbidden signs
  are the author's reading of each complaint. Generator: `evals/make_sign_cases.py`.
- `s08`-`s11` expect **no proposal**: by design only ORANGE and RED signs raise a proposal; a YELLOW sign on a GREEN
  patient is logged only. The cases still score whether the model finds the sign. Whether a YELLOW sign should raise
  a proposal is an open question for the nurse review.
- French (`s03`) and Swahili (`s04`, `s09`, `s13`) wording is the author's and should be checked by a native speaker.
- Split: `held_out`. Changing a case after its first run must be recorded here and the case moved to `tuning`.
