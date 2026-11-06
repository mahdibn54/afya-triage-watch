"""What the proposal card shows, built by code (api.md section 6, payload fields of Q4/Q13).

The trigger, the colour, the reasons, the evidence rows and the dedup key come from fixed code only. The model's
contribution (E5-4) is merged by `merge_decision` (E5-5: it can only add) and its rationale passes `rationale_text`
(E5-6: wording filter) before it is shown.
"""
from __future__ import annotations

import re
from typing import Any

from afya_mcp import rules, workflow

LABELS = {"resp_rate": "respiratory rate", "heart_rate": "heart rate", "systolic_bp": "systolic blood pressure",
          "temperature": "temperature", "spo2": "SpO2", "mobility": "mobility", "consciousness": "consciousness",
          "trauma": "trauma"}


def evidence_rows(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One row per input whose value changed between the previous and this reading (visit_timeline readings), with
    the record id of each side. band_changed: the input moved into a higher score band."""
    if not before or not after:
        return []
    rows = []
    for name, a in after["values"].items():
        b = before["values"].get(name)
        if b is None or b["value"] == a["value"]:
            continue
        rows.append({"input": name, "unit": a.get("unit"),
                     "before": {"obs_id": before["obs_id"], "value": b["value"], "points": b.get("points")},
                     "after": {"obs_id": after["obs_id"], "value": a["value"], "points": a.get("points")},
                     "band_changed": (a.get("points") or 0) > (b.get("points") or 0)})
    return rows


def _num(v: Any) -> str:
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def code_sentence(trigger: dict[str, Any], tews_before: int | None, tews_after: int | None,
                  evidence: list[dict[str, Any]], sign_codes: list[str], chart: dict[str, Any]) -> str:
    """The rationale built by code from measured changes and sign codes only (used when the model is down, gave
    nothing, or its text failed the wording filter). Never names a condition, cause, drug or treatment."""
    parts = [f"{LABELS.get(r['input'], r['input'])} {_num(r['before']['value'])} to {_num(r['after']['value'])}"
             for r in evidence if r["band_changed"]]
    frm, to = trigger.get("from"), trigger.get("to")
    if trigger.get("kind") == "colour_rise":
        moved = f"the score moved from {tews_before} to {tews_after}" if tews_before is not None \
            else f"the score is {tews_after}"
        text = (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]) + ": " if parts else ""
        out = f"{text}{moved} ({frm} to {to})."
    elif trigger.get("kind") == "sign":
        names = ", ".join(f"{c} ({chart['signs'][c]['gloss']})" for c in sign_codes if c in chart["signs"]) or "a sign"
        out = f"Warning sign {names} reported as current; the score is {tews_after} ({frm} confirmed, {to} proposed)."
    else:
        out = f"Nurse-reported worsening; the score is {tews_after} ({frm} confirmed, {to} proposed)."
    out = out[0].upper() + out[1:] + " Please take a second look."
    return out[: workflow.MAX_RATIONALE]


# E5-6: words that name a condition, a cause, a guess, a drug, a dose or a treatment. A rationale containing any of
# them is not shown; the code-built sentence replaces it (logged). Word-boundary, case-insensitive.
DENYLIST = [
    r"seps\w*", r"septic\w*", r"pneumon\w*", r"malaria\w*", r"infect\w*", r"diagnos\w*", r"likely", r"unlikely",
    r"suspect\w*", r"probabl\w*", r"possibl\w*", r"suggest\w*", r"consistent with", r"indicat\w*", r"give",
    r"giv(?:ing|en)", r"administer\w*", r"mg", r"mcg", r"ml", r"dose\w*", r"dosage", r"antibiotic\w*",
    r"paracetamol", r"acetaminophen", r"ibuprofen", r"amoxicillin", r"aspirin", r"artemether\w*", r"medication\w*",
    r"medicine\w*", r"drugs?", r"prescri\w*", r"treat\w*", r"therap\w*", r"iv fluids?", r"covid\w*",
    r"tuberculosis", r"tb", r"hiv", r"asthma\w*", r"copd", r"stroke", r"heart attack", r"cancer", r"dehydrat\w*",
    r"shock", r"caus\w*", r"due to", r"because of", r"conditions?", r"disease\w*", r"syndrome\w*", r"failure",
    r"fever", r"febrile", r"hypoxi\w*", r"tachycardi\w*", r"tachypn\w*", r"bacteri\w*", r"viral", r"virus",
]
_DENY = re.compile(r"\b(" + "|".join(DENYLIST) + r")\b", re.IGNORECASE)


def rationale_text(model_text: str | None, code_text: str) -> tuple[str, str, str | None]:
    """E5-6: (text shown, rationale_source, why the model's text was replaced or None). The model's rationale is
    shown only if it is non-empty, at most 300 characters and free of every denylisted word; otherwise the sentence
    built by code from the measured changes is shown instead."""
    text = " ".join((model_text or "").split())
    if not text:
        return code_text, "code", "no model rationale"
    if len(text) > workflow.MAX_RATIONALE:
        return code_text, "code", "too long"
    m = _DENY.search(text)
    if m:
        return code_text, "code", f"denylist: {m.group(1).lower()[:24]}"
    return text, "model", None


def merge_decision(dec: dict[str, Any], trigger: dict[str, Any], score: dict[str, Any], kept_signs: list[str],
                   chart: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """E5-5: the model can add urgency, never remove it. Code has already decided the trigger and always creates the
    proposal; from the model's decision only these additions are taken:
      - a re-measure request (action propose_and_remeasure),
      - a missing-value request (request_missing_value), only for an input the reading really lacks,
      - extra triggers, only sign codes that map_signs validated in this run (allow-listed, current, literal quote);
        they add a reason and can only raise the colour.
    Anything else is ignored and listed in the returned notes (logged in the trace). There is no field through which
    the model could lower the colour or cancel the proposal."""
    notes: list[str] = []
    action = dec.get("action") or "propose"
    missing = None
    if action not in workflow.AGENT_ACTIONS:
        notes.append("unknown action ignored")
        action = "propose"
    if action == "request_missing_value":
        if dec.get("missing_input") in (score.get("missing") or []):
            missing = dec["missing_input"]
        else:
            notes.append("missing-value request for an input that is not missing: ignored")
            action = "propose"
    extra = []
    for code in dec.get("extra_triggers") or []:
        if isinstance(code, str) and code in kept_signs and code in chart["signs"]:
            if code not in extra:
                extra.append(code)
        else:
            notes.append("extra trigger not among the validated signs: ignored")
    rank = rules.COLOUR_RANK.__getitem__
    to = max([trigger["to"], *(chart["signs"][c]["colour"] for c in extra
                               if chart["signs"][c]["colour"] in rules.URGENT_SIGN_COLOURS)], key=rank)
    reasons = list(trigger["reasons"]) + [f"agent added trigger: warning sign {c}" for c in extra]
    if action == "propose_and_remeasure":
        reasons.append("agent asks for a re-measure")
    if missing:
        reasons.append(f"agent asks for the missing value: {missing}")
    assert rank(to) >= rank(trigger["to"])   # never lower than the code's trigger
    return {"action": action, "missing_input": missing, "to_colour": to, "reasons": reasons,
            "extra_triggers": extra}, notes


def model_down(s: dict[str, Any]) -> bool:
    """E5-10: the model was needed in this run and did not answer (down, timeout, invalid output, breaker open or
    switched off). The card then says "no model"; the score, trigger and proposal are unchanged."""
    used = [str(s.get("signs", {}).get("model", "")), str((s.get("decision") or {}).get("model", ""))]
    return any(m.startswith("unavailable:") for m in used)


def build_payload(s: dict[str, Any], chart: dict[str, Any],
                  evidence: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """The proposal payload (workflow.PAYLOAD_FIELDS) from the run state. Returns it with the sign codes that go
    into the dedup key (allow-listed codes only, never quote text)."""
    sc, det, trig, signs = s["score"], s["det"], s["trigger"], s["signs"]
    merged, _notes = merge_decision(s.get("decision") or {}, trig, sc, signs["kept"], chart)
    prev = det.get("previous")
    rationale, source, _why = rationale_text((s.get("decision") or {}).get("rationale"),
                                             code_sentence(trig, prev["tews"] if prev else None, sc["tews"], evidence,
                                                           signs["kept"], chart))
    sign_codes = sorted({*signs["kept"], *(r["code"] for r in signs["rows"] if r["source"] == "reading")})
    cited = list(dict.fromkeys([*(r["before"]["obs_id"] for r in evidence), sc["observation_id"],
                                *([prev["observation_id"]] if prev else [])]))
    payload = {
        "to_colour": merged["to_colour"],
        "current_colour": det.get("confirmed_colour") or trig.get("from"),
        "tews_before": prev["tews"] if prev else None,
        "tews_after": sc["tews"],
        "reasons": merged["reasons"],
        "evidence": evidence,
        "signs": list(signs["rows"]),
        "rationale": rationale,
        "rationale_source": source,
        "notices": list(signs.get("notices", [])) + ([{"code": "model_unavailable"}] if model_down(s) else []),
        "agent_action": merged["action"],
        "missing_input": merged["missing_input"],
        "signs_verdict": signs.get("verdict"),
        "cited_obs_ids": cited,
    }
    if s.get("complaint"):   # the card shows the raw complaint (plain text), also when the model is down
        payload["complaint"] = s["complaint"]
    return payload, sign_codes
