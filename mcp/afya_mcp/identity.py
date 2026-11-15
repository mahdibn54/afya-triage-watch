"""Made-up patient identity for the demo waiting room (synthetic data only).

A name and a file number are derived from the synthetic label by a hash, so the same label always gets the same
ones. The names are short first names and surnames that are easy to say anywhere in the world. The seeded cases have
one fixed, unique name each; any other label gets a hashed combination. A result is never a real, identifiable person.
They are stored on the FHIR Patient and shown on screen only. They are never part of what the model sees
(get_queue_state's model-facing output, the WSO2 projection, prompts) or of an audit payload.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

FILE_NUMBER_SYSTEM = "urn:afya:file-number"

GIVEN = ("Ana", "Omar", "Lina", "Sam", "Maya", "Noah", "Zara", "Leo", "Nia", "Ravi", "Amir", "Sara",
         "Kofi", "Ada", "Ben", "Mia", "Eli", "Tara", "Jon", "Rosa", "Ivan", "Yara", "Theo", "Ines",
         "Hugo", "Nora", "Dan", "Lucia")
FAMILY = ("Cole", "Moyo", "Khan", "Silva", "Park", "Dube", "Reyes", "Bell", "Rao", "Costa", "Ali", "Diaz",
          "Brown", "Cruz", "Lee", "Hart", "Mensah", "Noor", "Stone", "Kim", "Wood", "Lopez", "Ford", "Shah",
          "Grant", "Pires", "Sato", "Boyd")

# Fixed on purpose: the P-014 demo patient is always Grace Achieng.
FIXED_NAMES = {"P-014": ("Grace", "Achieng")}

# The seeded waiting room (labels SYN-b01-..., SYN-n02-...): one short, easy-to-say name each, no repeated first or
# family name, so two patients are never mixed up on the board or in the video. Keyed by the case code in the label.
SEED_NAMES = {code: (GIVEN[i], FAMILY[(i * 5 + 3) % len(FAMILY)]) for i, code in enumerate(
    [f"b{n:02d}" for n in range(1, 21)] + ["n02", "m05", "m16", "n06", "m17", "m06", "s07"])}
_CASE_CODE = re.compile(r"^SYN-([a-z]\d\d)-")


def _digest(label: str) -> bytes:
    return hashlib.sha256(f"afya-identity:{label}".encode()).digest()


def name_for(label: str) -> tuple[str, str]:
    if label in FIXED_NAMES:
        return FIXED_NAMES[label]
    m = _CASE_CODE.match(label)
    if m and m.group(1) in SEED_NAMES:
        return SEED_NAMES[m.group(1)]
    d = _digest(label)
    return GIVEN[int.from_bytes(d[:4], "big") % len(GIVEN)], FAMILY[int.from_bytes(d[4:8], "big") % len(FAMILY)]


def file_number_for(label: str) -> str:
    return f"F-{int.from_bytes(_digest(label)[8:12], 'big') % 10000:04d}"


def identity_fields(label: str) -> dict[str, Any]:
    """The Patient.name entry and the file-number identifier for a label (label identifier is added by the caller)."""
    given, family = name_for(label)
    return {"name": [{"use": "official", "family": family, "given": [given], "text": f"{given} {family}"}],
            "file_number": {"system": FILE_NUMBER_SYSTEM, "value": file_number_for(label)}}


def full_name_of(patient: dict[str, Any]) -> str | None:
    for n in patient.get("name") or []:
        text = n.get("text") or " ".join([*n.get("given", []), n.get("family", "")]).strip()
        if text:
            return text
    return None


def file_number_of(patient: dict[str, Any]) -> str | None:
    return next((i["value"] for i in patient.get("identifier", []) if i.get("system") == FILE_NUMBER_SYSTEM
                 and i.get("value")), None)
