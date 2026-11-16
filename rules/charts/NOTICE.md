# Notice: SATS chart data

The files in `rules/charts/` are based on the **South African Triage Scale (SATS) Training Manual (2012)**
published by the Emergency Medicine Society of South Africa (EMSSA): https://emssa.org.za/sats

- What we took: the adult TEWS score bands, the colour categories and their time-to-be-seen targets,
  and the names of the adult warning signs, transcribed by the Afya authors into YAML.
- What we did not take: no text, figures or layout from the manual. Sign codes and short glosses are our own.
- **Permission:** EMSSA has given the authors permission to use this SATS chart data in this open-source project,
  released with the repository under the MIT licence (the permission is on file with the authors). The manual itself
  stays EMSSA's: its text, figures and layout are not reproduced here and are not licensed by this repository.
- This project is a research prototype on synthetic data. It is not clinically validated and has not been
  assessed or cleared as a medical device.

## Afya note (not chart content)

The pain-scale cutoffs are not in `sats_adult_2012.yaml`. The sign mapper's prompt maps patient-stated severity to
`SEVERE_PAIN` / `MODERATE_PAIN` from the patient's words, as SATS does (severe = unbearable, the worst ever; moderate =
intense but bearable). When a patient gives a number, the bands agreed with the nurse interviewed are 7-10 severe and
4-6 moderate (`FIELD_NOTES.md`), replacing the earlier working assumption of 8-10 and 5-7.
