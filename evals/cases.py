"""Case files: load and validate. One JSON file holds one case (object) or several (list); a directory is read
recursively, files in name order. Format documented in evals/README.md."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

COLOURS = ("GREEN", "YELLOW", "ORANGE", "RED")
SPLITS = ("tuning", "held_out", "fixture")
VALUE_KEYS = {"resp_rate", "heart_rate", "systolic_bp", "temperature", "spo2", "mobility", "consciousness", "trauma"}


class CaseError(ValueError):
    pass


@dataclass(frozen=True)
class Case:
    id: str
    age_years: int
    confirmed_colour: str
    readings: list[dict[str, Any]]            # [{"values": {...}, "complaint": str | None}]
    expected: dict[str, Any]                  # {"proposal": bool, "to_colour": str | None, "signs": [...], ...}
    split: str = "fixture"
    tags: list[str] = field(default_factory=list)
    title: str = ""
    arrived_minutes_ago: int = 30
    fhir_note: str | None = None              # free text written on the last Observation in FHIR (injection test)
    source: str = ""

    @property
    def positive(self) -> bool:
        return bool(self.expected["proposal"])


def _need(cond: bool, where: str, why: str) -> None:
    if not cond:
        raise CaseError(f"{where}: {why}")


def parse_case(raw: dict[str, Any], source: str = "") -> Case:
    cid = raw.get("id")
    where = f"{source}:{cid}"
    _need(isinstance(cid, str) and 1 <= len(cid) <= 40 and all(c.isalnum() or c == "-" for c in cid), where,
          "id must be 1-40 letters, digits or '-'")
    _need(raw.get("synthetic") is True, where, 'every case must say "synthetic": true (invented data only)')
    _need(raw.get("confirmed_colour") in COLOURS, where, f"confirmed_colour must be one of {COLOURS}")
    age = raw.get("age_years")
    _need(isinstance(age, int) and 0 <= age <= 120, where, "age_years must be an integer")
    readings = raw.get("readings")
    _need(isinstance(readings, list) and readings, where, "readings must be a non-empty list")
    for i, r in enumerate(readings):
        _need(isinstance(r, dict) and isinstance(r.get("values"), dict), where, f"readings[{i}].values missing")
        _need(set(r["values"]) <= VALUE_KEYS, where, f"readings[{i}].values has unknown keys")
        c = r.get("complaint")
        _need(c is None or isinstance(c, str), where, f"readings[{i}].complaint must be text or null")
    exp = raw.get("expected")
    _need(isinstance(exp, dict) and isinstance(exp.get("proposal"), bool), where, "expected.proposal (bool) missing")
    if exp["proposal"]:
        _need(exp.get("to_colour") in COLOURS, where, "expected.to_colour needed when a proposal is expected")
    for k in ("signs", "forbidden_signs", "notices"):
        _need(isinstance(exp.get(k, []), list), where, f"expected.{k} must be a list")
    split = raw.get("split", "fixture")
    _need(split in SPLITS, where, f"split must be one of {SPLITS}")
    note = raw.get("fhir_note")
    _need(note is None or isinstance(note, str), where, "fhir_note must be text")
    return Case(id=cid, age_years=age, confirmed_colour=raw["confirmed_colour"], readings=readings,
                expected={"proposal": exp["proposal"], "to_colour": exp.get("to_colour"),
                          "signs": list(exp.get("signs", [])), "forbidden_signs": list(exp.get("forbidden_signs", [])),
                          "notices": list(exp.get("notices", [])), "label_basis": exp.get("label_basis", "")},
                split=split, tags=list(raw.get("tags", [])), title=raw.get("title", ""),
                arrived_minutes_ago=int(raw.get("arrived_minutes_ago", 30)), fhir_note=note, source=source)


def load_cases(path: str | Path) -> list[Case]:
    p = Path(path)
    files = sorted(p.rglob("*.json")) if p.is_dir() else [p]
    if not files:
        raise CaseError(f"{p}: no .json case files")
    out: list[Case] = []
    for f in files:
        raw = json.loads(f.read_text(encoding="utf-8"))
        for item in raw if isinstance(raw, list) else [raw]:
            out.append(parse_case(item, f.name))
    ids = [c.id for c in out]
    dup = {i for i in ids if ids.count(i) > 1}
    _need(not dup, str(p), f"duplicate case ids: {sorted(dup)}")
    return out
