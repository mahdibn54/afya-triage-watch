"""SATS scoring as plain code. The LLM never calculates a score.

Rules are data (rules/charts/*.yaml); this module only reads and applies them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

COLOUR_RANK = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
RULES_DIR = Path(os.environ.get("RULES_DIR", Path(__file__).resolve().parents[2] / "rules"))


class NoChartForPatient(Exception):
    """The patient is outside every chart in the registry (e.g. a child before child charts exist)."""


@dataclass
class Score:
    chart_id: str
    tews: int                      # sum of the inputs that were present
    complete: bool                 # False if any input was missing (never guessed)
    missing: list[str]
    colour_by_tews: str            # lower bound when incomplete
    signs: list[str]               # signs implied by inputs (e.g. confused)
    colour: str                    # max(colour_by_tews, colour of every sign)
    points: dict[str, int] = field(default_factory=dict)
    cited: dict[str, str] = field(default_factory=dict)   # input -> observation id


def load_chart(chart_id: str = "sats_adult_2012", rules_dir: Path = RULES_DIR) -> dict[str, Any]:
    with open(rules_dir / "charts" / f"{chart_id}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_registry(rules_dir: Path = RULES_DIR) -> list[dict[str, Any]]:
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((rules_dir / "charts").glob("*.yaml"))]


def select_chart(age_years: float | None, height_cm: float | None, registry: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the chart that applies to this patient. Adult: over 12 years or over 150 cm."""
    for chart in registry:
        min_age = chart.get("min_age_years_exclusive")
        min_height = chart.get("min_height_cm_exclusive")
        if (age_years is not None and min_age is not None and age_years > min_age) or (
            height_cm is not None and min_height is not None and height_cm > min_height
        ):
            return chart
    raise NoChartForPatient("no chart for this patient yet")


def band_points(value: float, bands: list[dict[str, Any]]) -> int:
    for band in bands:
        if "lt" in band and value < band["lt"]:
            return band["points"]
        if "le" in band and value <= band["le"]:
            return band["points"]
        if "lt" not in band and "le" not in band:
            return band["points"]
    raise ValueError("bands must end with an unbounded row")


def colour_for(tews: int, chart: dict[str, Any]) -> str:
    for row in chart["colours"]:   # ordered highest first
        if tews >= row["min_tews"]:
            return row["colour"]
    raise ValueError("colours must cover 0")


def score(values: dict[str, Any], chart: dict[str, Any], cited: dict[str, str] | None = None) -> Score:
    """values: {"resp_rate": 26, "heart_rate": 112, ..., "mobility": "walking", "consciousness": "alert", "trauma": "no"}"""
    points: dict[str, int] = {}
    missing: list[str] = []
    signs: list[str] = []

    for name, spec in chart["numeric"].items():
        if values.get(name) is None:
            missing.append(name)
        else:
            points[name] = band_points(float(values[name]), spec["bands"])

    for name, spec in chart["categorical"].items():
        raw = values.get(name)
        if raw is None:
            missing.append(name)
            continue
        key = str(raw).lower()
        if key not in spec["values"]:
            raise ValueError(f"unknown value {raw!r} for {name}")
        points[name] = spec["values"][key]
        sign = spec.get("implies_sign", {}).get(key)
        if sign:
            signs.append(sign)

    tews = sum(points.values())
    by_tews = colour_for(tews, chart)
    colour = max([by_tews] + [chart["signs"][s]["colour"] for s in signs], key=COLOUR_RANK.__getitem__)
    return Score(
        chart_id=chart["chart_id"], tews=tews, complete=not missing, missing=missing,
        colour_by_tews=by_tews, signs=signs, colour=colour, points=points, cited=dict(cited or {}),
    )


def is_colour_rise(before: str, after: str) -> bool:
    return COLOUR_RANK[after] > COLOUR_RANK[before]
