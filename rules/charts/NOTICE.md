# Notice: SATS chart data

The files in `rules/charts/` are based on the **South African Triage Scale (SATS) Training Manual (2012)**
published by the Emergency Medicine Society of South Africa (EMSSA): https://emssa.org.za/sats

- What we took: the adult TEWS score bands, the colour categories and their time-to-be-seen targets,
  and the names of the adult warning signs, transcribed by the Afya authors into YAML.
- What we did not take: no text, figures or layout from the manual. Sign codes and short glosses are our own.
- The manual itself carries no open licence. These files are **not covered by the repository's MIT licence**.
  We have asked EMSSA for permission; until it is confirmed, use them for non-commercial research only.
- This project is a research prototype on synthetic data. It is not clinically validated and has not been
  assessed or cleared as a medical device.

## Afya note (not chart content)

The pain-scale cutoffs are not in `sats_adult_2012.yaml`. The sign mapper's prompt maps patient-stated severity to
`SEVERE_PAIN` / `MODERATE_PAIN`; Afya's working numbers (8-10 out of 10 severe, 5-7 moderate) are an assumption
**to be confirmed by the nurse review** (see `evals/cases/nurse_session/README.md`).
