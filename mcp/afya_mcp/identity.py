"""Made-up patient identity for the demo waiting room (synthetic data only).

A name and a file number are derived from the synthetic label by a hash, so the same label always gets the same
ones. The names are common Kenyan and South African first names and surnames, combined at random: a result is never a
real, identifiable person. They are stored on the FHIR Patient and shown on screen only. They are never part of what
the model sees (get_queue_state's model-facing output, the WSO2 projection, prompts) or of an audit payload.
"""
from __future__ import annotations

import hashlib
from typing import Any

FILE_NUMBER_SYSTEM = "urn:afya:file-number"

GIVEN = ("Amina", "Wanjiru", "Thabo", "Achieng", "Naledi", "Otieno", "Zanele", "Kamau", "Nomvula", "Wambui",
         "Sipho", "Atieno", "Lerato", "Kiprop", "Thandi", "Njeri", "Bongani", "Akinyi", "Palesa", "Mwangi",
         "Zodwa", "Chebet", "Lwazi", "Fatuma")
FAMILY = ("Nkosi", "Mokoena", "Otieno", "Kamau", "Dlamini", "Wekesa", "Khumalo", "Njoroge", "Mahlangu", "Kipchoge",
          "Ndlovu", "Mutua", "Zulu", "Omondi", "Sithole", "Wafula", "Molefe", "Kariuki", "Cele", "Abdi")

# Fixed on purpose: the P-014 demo patient is always Grace Achieng.
FIXED_NAMES = {"P-014": ("Grace", "Achieng")}


def _digest(label: str) -> bytes:
    return hashlib.sha256(f"afya-identity:{label}".encode()).digest()


def name_for(label: str) -> tuple[str, str]:
    if label in FIXED_NAMES:
        return FIXED_NAMES[label]
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
