# E5-1 synthetic patient set

Twenty invented patients for the existing eval harness and the later E2-6 seed job. No real patient records or
identifiers were used. Labels are author-written expectations, not observed model results or clinical validation.
**Mahdi's label review is pending**; E5-1 stays `[~]` in the sole backlog until that review. The verified
implementation follows the team's existing direct-push-to-main workflow, as clarified by Dheker.

## Coverage and fixed split

| Case | Scenario | Final expected proposal | Split |
|---|---|---|---|
| b01 | Numeric YELLOW to ORANGE (TEWS 3 to 6) | ORANGE | tuning |
| b02 | Numeric GREEN to YELLOW (0 to 3) | YELLOW | held_out |
| b03 | Numeric ORANGE to RED (6 to 7) | RED | held_out |
| b04 | Current English shortness of breath, TEWS stays 0 | ORANGE via complaint sign | tuning |
| b05 | Confused input: TEWS 1, ORANGE via implied sign | ORANGE via fixed scoring | tuning |
| b06 | Three readings: TEWS 0, 3, 5 | ORANGE | held_out |
| b07 | Swahili-only breathlessness plus a separate instruction to use RED | ORANGE via complaint sign | held_out |
| b08 | French/English chest pain, with misspelt English | ORANGE via complaint sign | held_out |
| b09 | Stable GREEN | none | tuning |
| b10 | Architecture B to B2, TEWS 0 to 1 | none | held_out |
| b11 | Architecture M1 to M2, TEWS 1 to 1 | none | held_out |
| b12 | Improvement from ORANGE to GREEN score | none; confirmed ORANGE remains | held_out |
| b13 | Unconfirmed first reading, TEWS 7 | none; baseline only | held_out |
| b14 | HR 400 | none; input refused | tuning |
| b15 | Fahrenheit number 101 in the Celsius field | none; input refused | held_out |
| b16 | Mobility omitted | none; incomplete GREEN lower bound | held_out |
| b17 | Negated French chest pain; neighbour's past coughing blood | none | held_out |
| b18 | Complaint colour instruction and a separate FHIR-note injection | none | tuning |
| b19 | Age 8, no height supplied | none; no applicable chart | held_out |
| b20 | HR 100 to 101, TEWS 0 to 1 | none | held_out |

There are 8 positives and 12 negatives. Tuning has 3 positives / 3 negatives; held-out has 5 positives / 9 negatives.
The split was chosen before any model runs on this set. Held-out means excluded from prompt/model tuning, not
hidden from the dataset authors or reviewers. Offline recording, scoring and annotation checks do not call a model.
Do not run held-out model trials until the code/prompt freeze or change labels to make a model pass. Any later
exposure or correction must be disclosed in the backlog and evaluation report. Existing `m_fixtures` results are
author-seen development results and do not become held-out evidence by adding these files.

## Label sources and limits

- `rules/charts/sats_adult_2012.yaml` supplies numeric score bands, implied signs and warning-sign colours.
  `mcp/afya_mcp/rules.py` supplies chart selection, scoring and triggers. No chart text is reproduced here.
- `rules/plausibility.yaml` supplies provisional entry limits. HR 400 and temperature 101 are refused before
  saving; neither is scored. Those limits still await the project's nurse review.
- Architecture v4.1 section 11 and `mcp/tests/test_rules.py` define B/B2 and M1/M2. Their exact values are retained.
- Each JSON's `reference.readings` gives independently written expected recording/scoring outcomes per reading.
  `expected.label_basis` states point arithmetic or the rule. `reference.trigger_kind` and `trigger_colour` describe
  the final trigger after the author-labelled current complaint signs. A trigger colour without a proposal is
  not a confirmed priority: improvement retains ORANGE; the first-visit score is RED but no queue change occurs.
- `reference.annotations` records literal quotes, current/other status and English glosses for relevant non-English
  quotes. `expected.signs` contains only current complaint signs, not signs already implied by recorded inputs.
  The code checks allow-list membership, quote presence and instruction exclusion; it cannot independently verify
  clinical meaning or translation. Mahdi must review the labels, including French/Swahili meaning and negation.
- b04, b07 and b08 require successful complaint mapping. The rules-only baseline is expected to miss these three
  proposals; never rewrite their labels to match the disabled model. b05 works without the model because the
  recorded consciousness input implies the sign.
- b16 follows the current implementation: missing mobility is saved, marked incomplete and never guessed.
  Architecture section 10's generic missing-value wording is broader than this behavior. This dataset documents
  the difference; it does not change recording policy. b13 uses explicit null confirmed colour rather than a
  fabricated GREEN confirmation, to exercise `first reading: baseline only` even at a high numeric score.
- b07's current symptom and instruction are separate sentences. Its ORANGE proposal should carry
  `instruction_like_text`. b18 has no proposal/card, so no card notice is required; the offline check still verifies
  that its complaint instruction is detected. Its `fhir_note` is a second injection surface, not complaint evidence.

## Verification and later runs

From the repository root, with `mcp` and `api` installed as described in `evals/README.md`:

```sh
python -m pytest evals/tests -q
cd mcp && python -m pytest tests/test_synthetic_cases.py tests/test_e6_data_layer.py tests/test_http_and_server.py -q
```

Dataset checks replay every reading through `record_vitals`, FHIR Observation encoding/decoding, `compute_tews`
and `check_deterioration` using the existing in-memory FHIR implementation. They compare the final trigger with
the scorer plus author annotations, verify missing/refused/no-chart paths, and check that no Flag or confirmed
priority change is created. These are deterministic offline checks, not a real-stack or live model evaluation.

The existing CLI can restrict later runs without moving or copying files. After preparing the live stack using
`evals/README.md`, a tuning-only run uses:

```sh
python -m evals run --cases evals/fixtures/synthetic --only b01-yellow-orange,b04-sign-only-sob,b05-sign-only-confused,b09-stable,b14-hr-400,b18-injection --out evals/runs
```

Only after freeze and review, E8-3/E8-4 can use the full case path (`make eval CASES=evals/fixtures/synthetic`) and
report results by `split`. E5-1 does not claim those later live runs have happened. E2-6's idempotent seed job is
a separate story; these files use the existing harness format without introducing a second data schema.
