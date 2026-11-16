# Afya Triage Watch: submission description

Healthcare track "The Triage Desk" · sub-theme *Deterioration Watch* · Team Afya

In a busy public outpatient department, one triage nurse may see dozens of patients a shift, and nobody is assigned
to watch the waiting room afterwards. A patient triaged GREEN can get worse on a bench for hours: a heart rate
creeping up, or a relative saying "he is confused since this morning". This is the *Deterioration Watch* sub-theme.

Afya Triage Watch is an agent that watches the waiting room for the triage nurse. Each time a reading is saved, a
LangGraph run scores it with SATS (the South African Triage Scale) in fixed code, compares it with earlier readings,
and reads the patient's own words in English, French or Swahili for warning signs such as vomiting blood. When a
patient may need a higher colour, or is overdue for a re-check, it proposes a **second look** citing the exact
readings and words. **The AI agent recommends. A human decides:** a nurse confirms every change before a FHIR Flag is
written. The agent never diagnoses, prescribes, moves a patient or lowers a colour.

It runs on an open-weights model (gpt-oss-120b) through our own MCP server: read tools for the model, act tools only
behind the nurse's approval, every call audited. It borrows WSO2's FHIR MCP server to read records.

A practising triage nurse reviewed the design; her answers set the re-check intervals and pain bands (FIELD_NOTES.md).

On 63 test cases, 3 runs each, it reached the right decision in 61, with 0 false alerts on the 31 cases where nothing
should fire; the SATS rules alone got 43. Both misses are documented in EVALS.md.

MIT-licensed, one command to run, synthetic data only; the nurse can dictate instead of typing, with no audio leaving
the device.
