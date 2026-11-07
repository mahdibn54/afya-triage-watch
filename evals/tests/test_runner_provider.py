"""E5-11: the eval runner picks the provider from the model tag, stops cleanly at a provider limit and resumes."""
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
        limit = "usage_limit" if case.id == "c2" else None
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


def test_groq_tag_picks_groq_with_low_reasoning_for_gpt_oss(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    s = runner.model_settings("groq:openai/gpt-oss-120b", "B", "u")
    assert (s.provider, s.model, s.groq_url, s.reasoning_effort, s.num_predict) == (
        "groq", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1", "low", 1024)
    assert runner.model_settings("groq:qwen/qwen3.8-27b", "B", "u").reasoning_effort is None
    assert runner.model_settings("groq:openai/gpt-oss-120b", "C", "u").model == runner.RULES_ONLY


def _fake_run(monkeypatch, limits):
    """run_trial stub: `limits` maps (case id, call number) -> provider limit of that attempt."""
    monkeypatch.setattr(runner, "HostGateway", lambda: None)

    async def warm_ok(self):
        return True
    monkeypatch.setattr(runner.Model, "warm_up", warm_ok)
    seen = []

    async def fake_trial(case, tag, group, i, settings, set_name, gw, batch, commit, cleanup=True):
        seen.append(case.id)
        lim = limits.get((case.id, seen.count(case.id)))
        return {"trial_id": f"{group}-{tag}-{case.id}-{i}", "proposal": None, "error": None, "tokens_in": 900,
                "tokens_out": 100, "model_unavailable": lim, "provider_limit": lim}
    monkeypatch.setattr(runner, "run_trial", fake_trial)
    return seen


def test_a_per_minute_limit_is_retried_after_a_pause_and_never_written(monkeypatch, tmp_path):
    seen = _fake_run(monkeypatch, {("c1", 1): "rate_limited"})
    pauses = []

    async def sleep(s):
        pauses.append(s)
    paths = asyncio.run(runner.run_all([Case("c1"), Case("c2")], ["groq:openai/gpt-oss-120b"], 1, 0, tmp_path,
                                       "set", "u", log=lambda *_: None, sleep=sleep))
    assert seen == ["c1", "c1", "c2"] and pauses == [runner.RATE_PAUSE_S]
    rows = [json.loads(x) for x in paths[0].read_text().splitlines()]
    assert [r["trial_id"] for r in rows] == ["B-groq:openai/gpt-oss-120b-c1-1", "B-groq:openai/gpt-oss-120b-c2-1"]
    assert all(r["provider_limit"] is None for r in rows)


def test_a_daily_limit_stops_and_resume_runs_only_what_is_missing(monkeypatch, tmp_path):
    cases = [Case("c1"), Case("c2"), Case("c3")]
    limits = {("c2", 1): "daily_limit"}
    seen = _fake_run(monkeypatch, limits)
    lines = []
    paths = asyncio.run(runner.run_all(cases, ["groq:openai/gpt-oss-120b"], 1, 0, tmp_path, "set", "u",
                                       log=lines.append))
    assert seen == ["c1", "c2"] and any("daily_limit" in x and "--resume" in x for x in lines)
    batch = paths[0].name.split("_")[0]
    seen.clear()
    limits.clear()                                                 # the next day
    paths = asyncio.run(runner.run_all(cases, ["groq:openai/gpt-oss-120b"], 1, 0, tmp_path, "set", "u",
                                       log=lines.append, resume=batch))
    assert seen == ["c2", "c3"]                                    # c1 was already written
    ids = [json.loads(x)["trial_id"].rsplit("-", 2)[1] for x in paths[0].read_text().splitlines()]
    assert ids == ["c1", "c2", "c3"] and len(list(tmp_path.iterdir())) == 1


def test_the_token_budget_stops_before_a_trial_that_would_not_fit(monkeypatch, tmp_path):
    seen = _fake_run(monkeypatch, {})
    lines = []
    paths = asyncio.run(runner.run_all([Case("c1"), Case("c2"), Case("c3")], ["groq:openai/gpt-oss-120b"], 1, 0,
                                       tmp_path, "set", "u", log=lines.append, token_budget=2500))
    assert seen == ["c1", "c2"] and len(paths[0].read_text().splitlines()) == 2   # 2 x 1000 used, a third: 3000
    assert any("token budget" in x for x in lines)
