"""E5-9: model settings and limits. Pure unit tests (no Postgres, no Ollama): a fake clock and fake transports."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from afya_api.model import CircuitBreaker, Model, ModelSettings, ModelUnavailable, OllamaBackend, Reply


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Scripted:
    """Backend that answers from a list: a Reply, an exception to raise, or 'hang' (never answers in time)."""

    def __init__(self, *answers) -> None:
        self.answers, self.seen = list(answers), []

    async def chat(self, messages, *, options, tools, format):
        self.seen.append({"messages": messages, "options": options, "tools": tools, "format": format})
        a = self.answers.pop(0)
        if a == "hang":
            await asyncio.sleep(10)
        if isinstance(a, BaseException):
            raise a
        return a

    async def digest(self):
        return "sha256:fake"


def run(coro):
    return asyncio.run(coro)


def test_ollama_request_sends_think_false_and_the_settings():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        call = {"function": {"name": "fhir_search", "arguments": {"count": 3}}}
        return httpx.Response(200, json={"model": "qwen3:8b",
                                         "message": {"role": "assistant", "content": "{}", "tool_calls": [call]},
                                         "prompt_eval_count": 120, "eval_count": 9, "load_duration": 2_000_000,
                                         "eval_duration": 900_000_000})

    s = ModelSettings(base_url="http://ollama.test")
    backend = OllamaBackend(s, transport=httpx.MockTransport(handler))
    reply = run(backend.chat([{"role": "user", "content": "x"}], options=s.options("map_signs"), tools=None,
                             format={"type": "object"}))
    assert seen["think"] is False and seen["stream"] is False and seen["keep_alive"] == "30m"
    assert seen["options"] == {"num_ctx": 8192, "num_predict": 384, "temperature": 0.0, "top_p": 0.8, "top_k": 20,
                               "seed": 42}
    assert seen["format"] == {"type": "object"} and "tools" not in seen
    assert s.options("investigate")["temperature"] == 0.2
    assert (reply.tokens_in, reply.tokens_out, reply.eval_ms) == (120, 9, 900.0)
    assert reply.tool_calls == [{"name": "fhir_search", "args": {"count": 3}}]


def test_timeout_then_breaker_opens_after_two_failures_and_closes_after_five_minutes():
    clock = Clock()
    backend = Scripted("hang", httpx.ConnectError("refused"), Reply("ok"))
    opened = []
    m = Model(backend, ModelSettings(call_timeout_s=0.05), clock=clock)

    async def on_open(reason):
        opened.append(reason)
    m.on_open = on_open
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([], "map_signs"))
    assert e.value.reason == "timeout" and not opened
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([], "map_signs"))
    assert e.value.reason == "unreachable" and opened == ["unreachable"]
    with pytest.raises(ModelUnavailable) as e:             # skipped without calling the backend
        run(m.call([], "map_signs"))
    assert e.value.reason == "circuit_open" and len(backend.seen) == 2
    clock.t += 301
    assert run(m.call([], "map_signs")).content == "ok"     # half-open: one call goes through, success closes it
    assert m.breaker.failures == 0 and m.breaker.open_until is None


def test_one_retry_on_invalid_json_with_the_error_included():
    backend = Scripted(Reply("not json"), Reply('{"verdict": "none", "signs": []}'))
    m = Model(backend)
    value, calls = run(m.call_json([{"role": "user", "content": "c"}], "map_signs", {"type": "object"}, json.loads))
    assert value == {"verdict": "none", "signs": []}
    assert [c.retried for c in calls] == [False, True] and calls[0].error.startswith("invalid")
    retry_msgs = backend.seen[1]["messages"]
    assert retry_msgs[-2] == {"role": "assistant", "content": "not json"} and "not valid" in retry_msgs[-1]["content"]


def test_second_invalid_answer_is_a_failure():
    m = Model(Scripted(Reply("x"), Reply("y")))
    with pytest.raises(ModelUnavailable) as e:
        run(m.call_json([], "map_signs", {}, json.loads))
    assert e.value.reason == "invalid_output" and m.breaker.failures == 1 and len(e.value.calls) == 2


def test_run_budget_goes_to_rules_only_without_counting_a_failure():
    clock = Clock()
    m = Model(Scripted(), ModelSettings(run_timeout_s=240), clock=clock)
    deadline = m.deadline()
    clock.t += 240
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([], "investigate", deadline=deadline))
    assert e.value.reason == "run_budget" and m.breaker.failures == 0


def test_call_timeout_is_capped_by_the_run_deadline():
    clock = Clock()
    m = Model(Scripted("hang"), ModelSettings(call_timeout_s=60), clock=clock)
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([], "investigate", deadline=clock.t + 1.05))
    assert e.value.reason == "timeout"


def test_warm_up_failure_is_not_counted_and_disabled_model_never_calls():
    m = Model(Scripted(httpx.ConnectError("down")))
    assert run(m.warm_up()) is False and m.breaker.failures == 0
    off = Model(Scripted(), enabled=False)
    with pytest.raises(ModelUnavailable) as e:
        run(off.call([], "map_signs"))
    assert e.value.reason == "disabled"


def test_breaker_counts_failures_in_a_row_only():
    b = CircuitBreaker(2, 300, Clock())
    assert b.failure() is False
    b.success()
    assert b.failure() is False and b.allow()
    assert b.failure() is True and not b.allow()


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    monkeypatch.setenv("MODEL", "qwen3:4b-instruct")
    monkeypatch.setenv("MODEL_SEED", "7")
    s = ModelSettings.from_env()
    assert (s.model, s.seed, s.call_timeout_s, s.run_timeout_s) == ("qwen3:4b-instruct", 7, 60.0, 240.0)
    assert run(Model(Scripted()).describe())["digest"] == "sha256:fake"
