"""Provider identity comes from recorded model metadata, never the billed price."""
from datetime import UTC, datetime

import pytest

from afya_api.routes_ui import trace_steps


@pytest.mark.parametrize("model", [
    {"provider": "groq", "served_by": "groq"},
    {"provider": "ollama", "served_by": None},
    {"provider": "openrouter", "served_by": "Nebius"},
    {},
])
def test_trace_exposes_only_provider_identity(model):
    payload = {"step_kind": "model", "name": "map_signs", "cost_usd": 0,
               "model": {**model, "private_detail": "not part of the trace contract"}}
    step = trace_steps([{"kind": "agent_step", "at": datetime.now(UTC), "payload": payload}])[0]
    result = step.model_dump()
    assert result["provider"] == model.get("provider")
    assert result["served_by"] == model.get("served_by")
    assert "private_detail" not in str(result)
    assert result["cost_usd"] == 0


def test_historical_trace_without_model_metadata_is_unknown():
    step = trace_steps([{"kind": "agent_step", "at": datetime.now(UTC), "payload": {
        "step_kind": "model", "name": "investigate", "cost_usd": 0}}])[0]
    assert step.model_dump()["provider"] is None
    assert step.model_dump()["served_by"] is None
