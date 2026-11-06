"""What the proposal card shows, built by code (api.md section 6, payload fields of Q4/Q13).

The trigger, the colour, the reasons, the evidence rows and the dedup key come from fixed code only. The model's
contribution (E5-4) is merged by `merge_decision` (E5-5: it can only add) and its rationale passes `rationale_text`
(E5-6: wording filter) before it is shown.
"""
from __future__ import annotations

from typing import Any

from afya_mcp import workflow

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


def build_payload(s: dict[str, Any], chart: dict[str, Any],
                  evidence: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """The proposal payload (workflow.PAYLOAD_FIELDS) from the run state. Returns it with the sign codes that go
    into the dedup key (allow-listed codes only, never quote text)."""
    sc, det, trig, signs, dec = s["score"], s["det"], s["trigger"], s["signs"], s.get("decision") or {}
    prev = det.get("previous")
    sign_codes = sorted({*signs["kept"], *(r["code"] for r in signs["rows"] if r["source"] == "reading")})
    cited = list(dict.fromkeys([*(r["before"]["obs_id"] for r in evidence), sc["observation_id"],
                                *([prev["observation_id"]] if prev else [])]))
    payload = {
        "to_colour": trig["to"],
        "current_colour": det.get("confirmed_colour") or trig.get("from"),
        "tews_before": prev["tews"] if prev else None,
        "tews_after": sc["tews"],
        "reasons": list(trig["reasons"]),
        "evidence": evidence,
        "signs": list(signs["rows"]),
        "rationale": code_sentence(trig, prev["tews"] if prev else None, sc["tews"], evidence, signs["kept"], chart),
        "rationale_source": "code",
        "notices": list(signs.get("notices", [])),
        "agent_action": dec.get("action") or "propose",
        "missing_input": dec.get("missing_input"),
        "signs_verdict": signs.get("verdict"),
        "cited_obs_ids": cited,
    }
    if s.get("complaint"):   # the card shows the raw complaint (plain text), also when the model is down
        payload["complaint"] = s["complaint"]
    return payload, sign_codes
