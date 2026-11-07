"""E5-11: the eval runner picks the provider from the model tag and stops cleanly at an Ollama Cloud plan limit."""
from __future__ import annotations

import asyncio
import json

from evals import runner


def test_model_tags_pick_the_provider(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "x")
    s = runner.model_settings("ollama_cloud:gpt-oss:120b", "B", "http://172.17.0.1:11434")
    assert (s.provider, s.model, s.ollama_cloud_url, s.think) == ("ollama_cloud", "gpt-oss:120b",
                                                                 "https://ollama.com", "low")
    assert runner.model_settings("qwen/qwen3-30b-a3b-instruct-2507", "B", "u").provider == "openrouter"
    local = runner.model_settings("qwen3:8b", "B", "http://172.17.0.1:11434")
    assert (local.provider, local.base_url, local.think) == ("ollama", "http://172.17.0.1:11434", False)
    assert runner.model_settings("ollama_cloud:gpt-oss:120b", "C", "u").model == runner.RULES_ONLY


class Case:
    def __init__(self, cid: str) -> None:
        self.id, self.expected = cid, {"proposal": False}


def test_a_plan_limit_stops_the_run_without_writing_that_trial(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "HostGateway", lambda: None)

    async def warm_ok(self):
        return True
    monkeypatch.setattr(runner.Model, "warm_up", warm_ok)
    seen = []

    async def fake_trial(case, tag, group, i, settings, set_name, gw, batch, commit, cleanup=True):
        seen.append(case.id)
        limit = "rate_limited" if case.id == "c2" else None
        return {"trial_id": f"{group}-{case.id}-{i}", "proposal": None, "error": None, "model_unavailable": limit}
    monkeypatch.setattr(runner, "run_trial", fake_trial)
    lines = []
    paths = asyncio.run(runner.run_all([Case("c1"), Case("c2"), Case("c3")], ["ollama_cloud:gpt-oss:120b"], 2, 0,
                                       tmp_path, "set", "u", log=lines.append))
    assert seen == ["c1", "c2"]                                   # sequential, nothing after the limit
    assert [json.loads(x)["trial_id"] for x in paths[0].read_text().splitlines()] == ["B-c1-1"]
    assert any(x.startswith("STOPPED") for x in lines)


def test_a_limit_at_warm_up_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "HostGateway", lambda: None)

    async def warm_limited(self):
        self.last = "usage_limit"
        return False
    monkeypatch.setattr(runner.Model, "warm_up", warm_limited)
    lines = []
    assert asyncio.run(runner.run_all([Case("c1")], ["ollama_cloud:gpt-oss:120b"], 1, 0, tmp_path, "set", "u",
                                      log=lines.append)) == []
    assert list(tmp_path.iterdir()) == [] and "usage_limit" in lines[-1]
