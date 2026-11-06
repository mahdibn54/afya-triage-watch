"""investigate: the model's read-only look at the record (architecture Appendix B, call B). E5-2 skeleton: no model
call yet, the code-built proposal stands as it is (action 'propose'). The bounded tool loop is E5-4."""
from __future__ import annotations

from typing import Any


async def investigate(ctx: Any, run_id: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {"action": "propose", "extra_triggers": [], "missing_input": None, "rationale": None, "cited_ids": [],
            "seen_ids": [], "model": "not_called"}
