"""map_signs: SATS warning signs for the card. E5-2 skeleton: only the signs implied by the reading itself (for
example reduced consciousness); the model call on the complaint is E5-3."""
from __future__ import annotations

from typing import Any


def reading_sign_rows(score: dict[str, Any], chart: dict[str, Any]) -> list[dict[str, Any]]:
    """Signs the fixed code derived from the inputs (compute_tews `signs`): no quote, source 'reading'."""
    return [{"code": c, "gloss": chart["signs"][c]["gloss"], "colour": chart["signs"][c]["colour"],
             "source": "reading", "status": "current", "quote": None, "quote_span": None, "reason": None}
            for c in dict.fromkeys(score.get("signs", [])) if c in chart["signs"]]


async def map_signs(ctx: Any, run_id: str, visit_id: str, complaint: str | None, score: dict[str, Any],
                    chart: dict[str, Any]) -> dict[str, Any]:
    return {"verdict": None, "kept": [], "rows": reading_sign_rows(score, chart), "notices": [],
            "model": "not_called"}
