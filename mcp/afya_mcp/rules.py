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
    if age_years is None and height_cm is None:
        raise NoChartForPatient("no chart: age and height unknown")
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
    """values: {"resp_rate": 26, "heart_rate": 112, ..., "mobility": "walking",
    "consciousness": "alert", "trauma": "no"}"""
    points: dict[str, int] = {}
    missing: list[str] = []
    signs: list[str] = []

    for name, spec in chart["numeric"].items():
        if values.get(name) is None:
            missing.append(name)
        else:
            value = float(values[name])
            if value != value:   # NaN would fall through every band to the top row
                raise ValueError(f"{name} is not a number")
            points[name] = band_points(value, spec["bands"])

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


# ---------- plausibility (E1-5) ----------

@dataclass
class Implausible:
    name: str
    value: float
    min: float
    max: float


def load_plausibility(rules_dir: Path = RULES_DIR) -> dict[str, Any]:
    with open(rules_dir / "plausibility.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_site(rules_dir: Path = RULES_DIR) -> dict[str, Any]:
    """Site rules (re-check intervals, reminder delays): not SATS, labelled with their source."""
    with open(rules_dir / "site.yaml", encoding="utf-8") as f:
        site = yaml.safe_load(f)
    for key in ("recheck_minutes", "clinician_reminder_after_minutes"):
        unknown = set(site.get(key, {})) - set(COLOUR_RANK)
        if unknown:
            raise ValueError(f"site.yaml {key}: unknown colours {sorted(unknown)}")
    return site


def target_minutes(chart: dict[str, Any], colour: str) -> int | None:
    """SATS time-to-be-seen target for a colour, from the chart (not from site rules)."""
    return next((row["target_minutes"] for row in chart["colours"] if row["colour"] == colour), None)


def check_plausible(values: dict[str, Any], plausibility: dict[str, Any]) -> list[Implausible]:
    """Return every value outside its limits. Empty list = plausible. Missing values are not checked here.

    Anything returned means: save nothing, score nothing, ask the nurse to re-measure.
    """
    problems: list[Implausible] = []
    for name, lim in plausibility["limits"].items():
        raw = values.get(name)
        if raw is None:
            continue
        value = float(raw)
        if not lim["min"] <= value <= lim["max"]:
            problems.append(Implausible(name, value, lim["min"], lim["max"]))
    return problems


# ---------- trigger rule (E1-6) ----------

URGENT_SIGN_COLOURS = {"ORANGE", "RED"}


@dataclass
class Trigger:
    kind: str | None          # "colour_rise" | "sign" | "nurse_reported" | None (log only)
    from_colour: str | None   # colour the nurse last confirmed (None = first reading)
    to_colour: str            # proposed colour; never lower than from_colour
    reasons: list[str]

    @property
    def propose(self) -> bool:
        return self.kind is not None


def evaluate_trigger(
    confirmed_colour: str | None,
    after: Score,
    model_signs: list[str],
    chart: dict[str, Any],
    nurse_reported_worsening: bool = False,
    previous_colour: str | None = None,
) -> Trigger:
    """Decide in code whether a new reading becomes a proposal. The model can never switch this off.

    confirmed_colour: the colour a nurse last confirmed for this visit (None on the first reading).
    after: score of the new reading (its colour already includes signs implied by inputs, e.g. "confused").
    model_signs: sign codes from map_signs that code has already validated (allow-list, current, literal quote).
    previous_colour: colour of the previous scored reading. Used as the reference only when no colour has been
    confirmed yet, so a visit that was never confirmed still gets a proposal when it worsens.
    Proposal only on: a colour rise, a current ORANGE/RED sign above the confirmed colour, or a nurse-reported
    worsening. Anything else is logged only. The agent never proposes a downgrade.
    """
    for code in model_signs:
        if code not in chart["signs"]:
            raise ValueError(f"sign {code!r} is not on the allow-list")

    note: list[str] = []
    if confirmed_colour is None:
        if previous_colour is None:
            return Trigger(None, None, after.colour, ["first reading: baseline only"])
        confirmed_colour = previous_colour
        note = ["no colour confirmed yet: compared with the previous reading"]
    incomplete = [] if after.complete else ["score incomplete: colour is a lower bound"]

    rank = COLOUR_RANK.__getitem__
    sign_colours = [chart["signs"][c]["colour"] for c in model_signs]
    urgent_sign_colours = [c for c in sign_colours if c in URGENT_SIGN_COLOURS]
    to_colour = max([confirmed_colour, after.colour, *urgent_sign_colours], key=rank)

    if rank(after.colour) > rank(confirmed_colour):
        reasons = [f"colour rise {confirmed_colour} -> {after.colour} (TEWS {after.tews})", *incomplete, *note]
        return Trigger("colour_rise", confirmed_colour, to_colour, reasons)

    if urgent_sign_colours and rank(max(urgent_sign_colours, key=rank)) > rank(confirmed_colour):
        signs = [c for c in model_signs if chart["signs"][c]["colour"] in URGENT_SIGN_COLOURS]
        return Trigger("sign", confirmed_colour, to_colour, [f"warning sign {', '.join(signs)}", *note])

    if nurse_reported_worsening:
        return Trigger("nurse_reported", confirmed_colour, to_colour, ["nurse reported worsening", *note])

    if rank(after.colour) < rank(confirmed_colour):
        return Trigger(None, confirmed_colour, confirmed_colour,
                       ["improved: logged only, never downgraded", *incomplete, *note])
    return Trigger(None, confirmed_colour, confirmed_colour, ["no colour change: logged only", *incomplete, *note])
