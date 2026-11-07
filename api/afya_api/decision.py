"""What the proposal card shows, built by code (api.md section 6, payload fields of Q4/Q13).

The trigger, the colour, the reasons, the evidence rows and the dedup key come from fixed code only. The model's
contribution (E5-4) is merged by `merge_decision` (E5-5: it can only add) and its rationale passes `rationale_text`
(E5-6: wording filter) before it is shown.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
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


# E5-6: words that name a condition, a cause, a guess, a drug, a dose, a treatment or a disposition (English, French,
# Swahili). A rationale containing any of them is not shown; the code-built sentence replaces it (logged). Checked on
# the NFKC, zero-width-stripped, case-folded text with word boundaries. This list only names the reason in the trace:
# the gate that lets text through is the allowed vocabulary below (E12-1, LLM audit B1).
DENYLIST = [
    r"seps\w*", r"septic\w*", r"pneumon\w*", r"malaria\w*", r"infect\w*", r"diagnos\w*", r"likely", r"unlikely",
    r"suspect\w*", r"probabl\w*", r"possibl\w*", r"suggest\w*", r"consistent with", r"indicat\w*", r"give",
    r"giv(?:ing|en)", r"administer\w*", r"mg", r"mcg", r"ml", r"dose\w*", r"dosage", r"antibiotic\w*",
    r"paracetamol", r"acetaminophen", r"ibuprofen", r"amoxicillin", r"aspirin", r"artemether\w*", r"medication\w*",
    r"medicine\w*", r"drugs?", r"prescri\w*", r"treat\w*", r"therap\w*", r"iv fluids?", r"fluids?", r"covid\w*",
    r"tuberculosis", r"tb", r"hiv", r"asthma\w*", r"copd", r"stroke", r"heart attack", r"cancer", r"dehydrat\w*",
    r"shock", r"caus\w*", r"due to", r"because of", r"conditions?", r"disease\w*", r"syndrome\w*", r"failure",
    r"fever", r"febrile", r"hypoxi\w*", r"tachycardi\w*", r"tachypn\w*", r"bacteri\w*", r"viral", r"virus",
    r"oxygen", r"o2", r"nebuli[sz]\w*", r"icu", r"admit\w*", r"admission", r"refer\w*", r"transfer\w*",
    r"hypotens\w*", r"hypertens\w*", r"bradycard\w*", r"pyrex\w*", r"meningit\w*", r"start\w*", r"begin",
    # French
    r"paludisme", r"septicémie", r"infectio\w*", r"pneumonie", r"traitement\w*", r"traiter", r"médicament\w*",
    r"donner", r"administrer", r"antibiotique\w*", r"probable\w*", r"diagnostic\w*", r"fièvre", r"maladie\w*",
    r"hospitalis\w*", r"oxygène", r"perfusion\w*",
    # Swahili
    r"dawa", r"apewe", r"apatiwe", r"mpe", r"sindano", r"homa", r"nimonia", r"kifua kikuu", r"ugonjwa", r"maambukizi",
    r"kulazwa", r"hospitali", r"tibu", r"matibabu",
]
_DENY = re.compile(r"\b(" + "|".join(DENYLIST) + r")\b", re.IGNORECASE)

# E12-1 (LLM audit B1): the model's rationale is shown only if EVERY word is on this small vocabulary (measured
# inputs, how they moved, scores, colours, record words), plus the chart's sign codes and glosses; every number is a
# number of this run's readings, scores or points; and every record id is one the run's facts or tools returned.
# Anything else -> the code-built sentence. This makes the wording a whitelist, not a blacklist.
VOCABULARY = frozenset("""
a an the and or with in on at of to from by as per for than since between over under after before while also both
each only still more less same new now then this that these those its their it is are was were has have had been be
heart rate respiratory resp breathing breaths breath beats pulse systolic diastolic blood pressure bp temperature temp
spo2 saturation mobility consciousness alert walking trauma avpu pain
score scores tews sats colour color colours red orange yellow green blue
reading readings measurement measurements value values input inputs band bands point points pts sign signs warning
previous earlier latest current first second third last prior recent recorded record records id ids observation
observations encounter visit proposal proposed confirmed trigger triggered threshold chart adult
rose risen rise rises rising raised raising increased increase increases increasing went up down fell fallen
dropped drop decreased decrease changed change changes moved move stayed unchanged higher lower above below
reached reaching crossed into out stable steady
re remeasure measure measured repeat repeated again missing not no none reported patient nurse
please take look review check second-look minutes minute min bpm mmhg mm hg c cel celsius degrees per percent
one two three four five
""".split())
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u00ad\u180e\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d"
                                   "\u202e\u2060\u2061\u2062\u2063\u2064\u2066\u2067\u2068\u2069\ufeff"), None)
_ID = re.compile(r"\b(observation|encounter)/([a-z0-9.-]{1,64})", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")
_PUNCT = re.compile(r"[\s.,;:()\[\]/%°+\-'\"<>=→←↑↓–—]+")


def clean_text(text: str) -> str:
    """NFKC, zero-width and bidi controls removed, case-folded, whitespace collapsed."""
    return " ".join(unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).casefold().split())


def _number(v: Any) -> str:
    return format(float(v), "g")


@dataclass(frozen=True)
class RationaleFacts:
    """What a rationale may mention: numbers and record ids from this run, extra words (the chart's sign codes and
    glosses)."""
    numbers: frozenset[str] = frozenset()
    ids: frozenset[str] = frozenset()
    words: frozenset[str] = frozenset()


def rationale_facts(*sources: Any, ids: list[str] | None = None, chart: dict[str, Any] | None = None
                    ) -> RationaleFacts:
    """Collect every number and record id in `sources` (score, deterioration check, evidence rows, readings, trigger),
    plus `ids` (record ids the investigate tools returned) and the chart's sign codes and gloss words."""
    numbers: set[str] = set()
    found: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            numbers.add(_number(v))
        elif isinstance(v, str):
            for kind, rid in _ID.findall(v):
                found.add(f"{kind.casefold()}/{rid.casefold()}")
                if rid.isdigit():
                    numbers.add(_number(rid))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple, set)):
            for x in v:
                walk(x)
    walk(list(sources))
    walk(list(ids or []))
    words: set[str] = set()
    for code, sign in ((chart or {}).get("signs") or {}).items():
        words.add(code.casefold())
        words.update(w for w in _PUNCT.split(clean_text(sign.get("gloss", ""))) if w)
    return RationaleFacts(frozenset(numbers), frozenset(found), frozenset(words))


def rationale_text(model_text: str | None, code_text: str,
                   facts: RationaleFacts | None = None) -> tuple[str, str, str | None]:
    """E5-6 / E12-1: (text shown, rationale_source, why the model's text was replaced or None). The model's rationale
    is shown only if it is non-empty, at most 300 characters, free of every denylisted word, cites only record ids and
    numbers from this run (`facts`; none given = none allowed) and uses only allowed words. Otherwise the sentence
    built by code from the measured changes is shown instead."""
    facts = facts or RationaleFacts()
    raw = " ".join((model_text or "").split())
    if not raw:
        return code_text, "code", "no model rationale"
    if len(raw) > workflow.MAX_RATIONALE:
        return code_text, "code", "too long"
    text = clean_text(raw)
    m = _DENY.search(text)
    if m:
        return code_text, "code", f"denylist: {m.group(1).lower()[:24]}"
    for kind, rid in _ID.findall(text):
        if f"{kind}/{rid}" not in facts.ids:
            return code_text, "code", "record id not in this run's evidence"
    rest = _ID.sub(" ", text)
    for n in _NUMBER.findall(rest):
        if _number(n.replace(",", ".")) not in facts.numbers:
            return code_text, "code", f"number not in this run's evidence: {n[:12]}"
    rest = _NUMBER.sub(" ", rest)
    allowed = VOCABULARY | facts.words
    bad = next((w for w in _PUNCT.split(rest) if w and w not in allowed), None)
    if bad is not None:   # E12-5: the first rejected word is named (as the denylist reason does) to measure the filter
        return code_text, "code", f"word outside the allowed vocabulary: {bad[:24]}"
    return raw, "model", None


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


def facts_for(s: dict[str, Any], chart: dict[str, Any], evidence: list[dict[str, Any]],
              readings: list[dict[str, Any]] | None = None) -> RationaleFacts:
    """What this run's rationale may cite: its score, deterioration check, trigger, evidence rows, the two readings
    (all their values) and the record ids its investigate tools returned."""
    dec = s.get("decision") or {}
    return rationale_facts(s.get("score"), s.get("det"), s.get("trigger"), evidence, readings or [],
                           ids=list(dec.get("seen_ids") or []), chart=chart)


def build_payload(s: dict[str, Any], chart: dict[str, Any], evidence: list[dict[str, Any]],
                  readings: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], list[str]]:
    """The proposal payload (workflow.PAYLOAD_FIELDS) from the run state. Returns it with the sign codes that go
    into the dedup key (allow-listed codes only, never quote text)."""
    sc, det, trig, signs = s["score"], s["det"], s["trigger"], s["signs"]
    merged, _notes = merge_decision(s.get("decision") or {}, trig, sc, signs["kept"], chart)
    prev = det.get("previous")
    rationale, source, _why = rationale_text((s.get("decision") or {}).get("rationale"),
                                             code_sentence(trig, prev["tews"] if prev else None, sc["tews"], evidence,
                                                           signs["kept"], chart),
                                             facts_for(s, chart, evidence, readings))
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
