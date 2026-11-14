# Afya Triage Watch: submission description

Healthcare track "The Triage Desk" · sub-theme *Deterioration Watch* · Team Afya

In a busy public outpatient department, one triage nurse may see dozens of patients a shift. After triage, nobody is
assigned to watch the waiting room. A patient triaged GREEN can get worse on a bench for hours: a heart rate
creeping up, or a relative saying "he is confused since this morning". SATS, the South African Triage Scale, asks for
waiting patients to be re-checked, but the people to do it are rarely there.

Afya Triage Watch is an agent that watches the waiting room for the triage nurse. Each time a reading is saved, a
LangGraph run scores it with SATS in fixed code, checks it against the patient's earlier readings, and reads the
patient's own words in English, French or Swahili for warning signs such as vomiting blood or confusion. When a
patient may need a higher colour, or is overdue for a re-check, it proposes a **second look** and cites the exact
readings and words behind it. **The AI agent recommends. A human decides:** a nurse confirms every change, and only
then is a FHIR Flag written. The agent never diagnoses, prescribes, moves a patient or lowers a colour.

It runs on an open-weights model (gpt-oss-120b) through our own MCP server: read tools for the model, act tools only
behind the nurse's approval, every call audited. It borrows WSO2's FHIR MCP server to read records. Fixed code
computes every score; the model only adds signs that code then verifies.

On 63 written test cases, 3 runs each, it reached the right decision in 61, with 0 false alerts on the 31 cases
where nothing should fire. The SATS rules alone got 43. Both misses are documented in EVALS.md.

Everything is MIT-licensed, runs with one command on synthetic data, and the nurse can dictate instead of typing,
in the browser, with no audio leaving the device.
