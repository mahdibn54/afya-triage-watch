"""The eval's own check for diagnosis / cause / treatment wording in a SHOWN rationale. Independent of the product's
filter (api/afya_api/decision.py DENYLIST) and wider than it, so a hole in the filter can show up here."""
from __future__ import annotations

import re

WORDS = [
    r"diagnos\w*", r"differential", r"likely", r"unlikely", r"probabl\w*", r"possibl\w*", r"suspect\w*", r"suggest\w*",
    r"consistent with", r"indicat\w*", r"sign of", r"symptom of", r"due to", r"because of", r"caused?", r"causing",
    r"seps\w*", r"septic\w*", r"pneumon\w*", r"malaria\w*", r"infect\w*", r"bacteri\w*", r"viral", r"virus", r"flu",
    r"asthma\w*", r"copd", r"embol\w*", r"infarct\w*", r"heart attack", r"cardiac", r"stroke", r"angina", r"cancer",
    r"tuberculosis", r"tb", r"hiv", r"covid\w*", r"anaemi\w*", r"anemi\w*", r"dehydrat\w*", r"shock", r"hypoxi\w*",
    r"tachycardi\w*", r"tachypn\w*", r"hypotens\w*", r"hypertens\w*", r"fever", r"febrile", r"disease\w*",
    r"syndrome\w*", r"disorder\w*", r"condition\w*", r"failure",
    r"treat\w*", r"therap\w*", r"medicat\w*", r"medicine\w*", r"drugs?", r"prescri\w*", r"antibiotic\w*",
    r"paracetamol", r"acetaminophen", r"ibuprofen", r"amoxicillin", r"aspirin", r"artemether\w*", r"morphine",
    r"oxygen", r"nebulis\w*", r"salbutamol", r"fluids?", r"iv", r"dose\w*", r"dosage", r"mg", r"mcg", r"ml",
    r"administer\w*", r"give", r"giving", r"given", r"start\s+\w+\s+(?:on|with)", r"intubat\w*", r"cannula",
]
_RX = re.compile(r"\b(" + "|".join(WORDS) + r")\b", re.IGNORECASE)


def violations(text: str | None) -> list[str]:
    """The forbidden words found in the text (lower-case, in order of appearance)."""
    return [m.group(1).lower() for m in _RX.finditer(text or "")]
