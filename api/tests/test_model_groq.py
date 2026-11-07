"""E5-11: Groq provider (free plan, open-weights model). httpx MockTransport only, no network."""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from afya_api import model as model_mod
from afya_api.model import (
    GroqBackend,
    Model,
    ModelSettings,
    ModelUnavailable,
    RateState,
    _duration_s,
    backend_for,
)

GKEY = "gsk-test-not-a-real-key"
GQ = ModelSettings(provider="groq", model="openai/gpt-oss-120b", groq_url="http://groq.test/openai/v1",
                   reasoning_effort="low", num_predict=1024, backoff_s=0.0)
LIMIT_HEADERS = {"x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "7000",
                 "x-ratelimit-reset-tokens": "7.5s", "x-ratelimit-limit-requests": "1000",
                 "x-ratelimit-remaining-requests": "990", "x-ratelimit-reset-requests": "2m59.56s"}


@pytest.fixture(autouse=True)
def fresh_rates():
    model_mod._GROQ_RATES.clear()
    yield
    model_mod._GROQ_RATES.clear()


def run(coro):
    return asyncio.run(coro)


def answer(content="", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"id": "chatcmpl-1", "model": "openai/gpt-oss-120b", "choices": [{"message": msg, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020},
            "x_groq": {"id": "req_1", "seed": 7}}


def ok(content="", tool_calls=None, headers=None):
    return httpx.Response(200, json=answer(content, tool_calls), headers=headers or LIMIT_HEADERS)


def daily_429():
    return httpx.Response(429, headers={"retry-after": "2400"}, json={"error": {
        "message": "Rate limit reached for model `openai/gpt-oss-120b` on tokens per day (TPD): Limit 200000, "
                   "Used 199500, Requested 1500. Please try again in 40m.", "type": "tokens",
        "code": "rate_limit_exceeded"}})


def test_groq_request_is_openai_shaped_with_strict_schema_and_no_openrouter_fields():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        seen.update(json.loads(request.content))
        return ok('{"verdict": "none", "signs": []}')

    backend = GroqBackend(GQ, transport=httpx.MockTransport(handler), api_key=GKEY)
    reply = run(backend.chat([{"role": "user", "content": "x"}], options=GQ.options("map_signs", seed=7),
                             tools=None, format={"type": "object"}))
    assert seen["url"] == "http://groq.test/openai/v1/chat/completions" and seen["auth"] == f"Bearer {GKEY}"
    assert seen["model"] == "openai/gpt-oss-120b"
    assert (seen["temperature"], seen["top_p"], seen["seed"], seen["max_completion_tokens"]) == (0.0, 0.8, 7, 1024)
    assert (seen["reasoning_effort"], seen["include_reasoning"]) == ("low", False)
    assert seen["response_format"] == {"type": "json_schema", "json_schema": {"name": "answer", "strict": True,
                                                                              "schema": {"type": "object"}}}
    for absent in ("top_k", "provider", "usage", "max_tokens", "tools"):
        assert absent not in seen
    assert (reply.tokens_in, reply.tokens_out, reply.cost_usd, reply.provider) == (900, 120, 0.0, "groq")
    assert reply.model == "openai/gpt-oss-120b"
    assert GKEY not in repr(backend)


def test_groq_tool_calls_round_trip_with_ids():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        call = {"id": "fc_1", "type": "function", "function": {"name": "fhir_search", "arguments": '{"count": 3}'}}
        return ok(tool_calls=[call])

    backend = GroqBackend(GQ, transport=httpx.MockTransport(handler), api_key=GKEY)
    history = [{"role": "system", "content": "s"},
               {"role": "assistant", "content": "", "tool_calls": [{"id": "call_0_0", "function": {
                   "name": "get_queue_state", "arguments": {}}}]},
               {"role": "tool", "content": "{}", "tool_name": "get_queue_state", "tool_call_id": "call_0_0"}]
    tools = [{"type": "function", "function": {"name": "fhir_search", "parameters": {"type": "object"}}}]
    reply = run(backend.chat(history, options=GQ.options("investigate"), tools=tools, format=None))
    assert reply.tool_calls == [{"name": "fhir_search", "args": {"count": 3}}]
    assert seen["messages"][2] == {"role": "tool", "tool_call_id": "call_0_0", "content": "{}"}
    assert seen["tools"] == tools and seen["tool_choice"] == "auto" and "response_format" not in seen


def test_groq_is_refused_without_synthetic_data_or_key_and_nothing_is_sent():
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or ok("{}"))
    real = ModelSettings(provider="groq", groq_url="http://groq.test", data_classification="real")
    m = Model(GroqBackend(real, transport=transport, api_key=GKEY), real)
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([{"role": "user", "content": "x"}], "map_signs"))
    assert e.value.reason == "data_not_synthetic" and m.breaker.failures == 0
    with pytest.raises(ModelUnavailable):      # the backend refuses on its own too
        run(GroqBackend(real, transport=transport, api_key=GKEY).chat([], options=real.options("warm_up")))
    nokey = Model(GroqBackend(GQ, transport=transport, api_key=""), GQ)
    with pytest.raises(ModelUnavailable) as e:
        run(nokey.call([], "map_signs"))
    assert e.value.reason == "no_api_key" and nokey.breaker.failures == 0 and calls == []
    assert run(nokey.warm_up()) is False and nokey.status()["refused"] == "no_api_key" and calls == []


def test_a_429_with_a_short_retry_after_is_honoured_in_full():
    waits = []

    async def sleep(s):
        waits.append(s)

    answers = [httpx.Response(429, headers={"retry-after": "12"}, json={"error": {"message": "tokens per minute"}}),
               ok("fine")]
    backend = GroqBackend(GQ, transport=httpx.MockTransport(lambda r: answers.pop(0)), api_key=GKEY, sleep=sleep)
    m = Model(backend, GQ)
    assert run(m.call([], "investigate")).content == "fine" and m.breaker.failures == 0
    assert waits == [12.0]         # not capped at backoff_cap_s (8 s): the full retry-after, it fits in 60 s


def test_a_429_that_does_not_fit_the_call_is_rate_limited_and_counted_by_the_breaker():
    sent = []

    def handler(r):
        sent.append(r)
        return httpx.Response(429, headers={"retry-after": "75"}, json={"error": {"message": "per minute (TPM)"}})

    m = Model(GroqBackend(GQ, transport=httpx.MockTransport(handler), api_key=GKEY), GQ)
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([], "investigate"))
    assert e.value.reason == "rate_limited" and len(sent) == 1 and m.breaker.failures == 1


def test_a_daily_limit_is_never_retried_and_opens_the_breaker_after_two():
    sent = []
    m = Model(GroqBackend(GQ, transport=httpx.MockTransport(lambda r: sent.append(r) or daily_429()), api_key=GKEY),
              GQ)
    for _ in range(2):
        with pytest.raises(ModelUnavailable) as e:
            run(m.call([], "map_signs"))
        assert e.value.reason == "daily_limit"
    assert len(sent) == 2 and m.breaker.state == "open"
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([], "map_signs"))
    assert e.value.reason == "circuit_open" and len(sent) == 2
    w = Model(GroqBackend(GQ, transport=httpx.MockTransport(lambda r: daily_429()), api_key=GKEY), GQ)
    assert run(w.warm_up()) is False and w.last == "daily_limit" and w.breaker.failures == 0


def test_pacing_waits_for_the_tokens_per_minute_budget_from_the_headers():
    waits = []

    async def sleep(s):
        waits.append(s)

    low = {**LIMIT_HEADERS, "x-ratelimit-remaining-tokens": "200", "x-ratelimit-reset-tokens": "55s"}
    answers = [ok("a", headers=low), ok("b")]
    backend = GroqBackend(GQ, transport=httpx.MockTransport(lambda r: answers.pop(0)), api_key=GKEY, sleep=sleep)
    m = Model(backend, GQ)
    run(m.call([], "investigate"))
    assert waits == []
    run(m.call([], "investigate"))
    # about 1024 + a few tokens needed, 200 left, 8000/min refill -> ~6-7 s, never more than the 55 s reset
    assert len(waits) == 1 and 5.0 < waits[0] < 10.0
    # a second backend of the same process (the eval runner makes one per trial) sees the same budget
    assert GroqBackend(GQ, api_key=GKEY).rates is backend.rates


def test_pacing_that_cannot_fit_the_call_is_rate_limited_without_sending():
    sent = []
    st = model_mod._GROQ_RATES.setdefault(GQ.groq_url, RateState())
    st.tokens_limit, st.tokens_left, st.tokens_reset_at = 600, 0, 1e12     # 10 tokens/s: ~100 s for 1024 tokens
    m = Model(GroqBackend(GQ, transport=httpx.MockTransport(lambda r: sent.append(r) or ok()), api_key=GKEY), GQ)
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([], "investigate"))
    assert e.value.reason == "rate_limited" and sent == [] and m.breaker.failures == 1


def test_no_requests_left_today_is_a_daily_limit_without_sending():
    sent = []
    st = model_mod._GROQ_RATES.setdefault(GQ.groq_url, RateState())
    st.requests_left, st.requests_reset_at = 0, 1e12
    m = Model(GroqBackend(GQ, transport=httpx.MockTransport(lambda r: sent.append(r) or ok()), api_key=GKEY), GQ)
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([], "map_signs"))
    assert e.value.reason == "daily_limit" and sent == []


def test_groq_calls_are_queued_one_at_a_time():
    active, peak = [0], [0]

    async def handler(request: httpx.Request) -> httpx.Response:
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(0.01)
        active[0] -= 1
        return httpx.Response(200, json=answer("ok"))

    backend = GroqBackend(GQ, transport=httpx.MockTransport(handler), api_key=GKEY)

    async def three():
        await asyncio.gather(*(backend.chat([], options=GQ.options("investigate")) for _ in range(3)))
    run(three())
    assert peak[0] == 1


def test_groq_settings_from_env_and_the_key_is_never_exposed(monkeypatch, caplog):
    for k in ("GROQ_MODEL", "GROQ_BASE_URL", "GROQ_CONCURRENCY", "MODEL_REASONING_EFFORT", "MODEL_NUM_PREDICT",
              "DATA_CLASSIFICATION"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MODEL_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", GKEY)
    s = ModelSettings.from_env()
    assert (s.provider, s.model, s.groq_url, s.reasoning_effort, s.num_predict, s.groq_concurrency) == (
        "groq", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1", "low", 1024, 1)
    m = Model(backend_for(s), s)
    assert isinstance(m.backend, GroqBackend)
    assert m.status()["provider"] == "groq" and m.status()["refused"] is None
    assert GKEY not in repr(s) and GKEY not in repr(m.backend) and GKEY not in json.dumps(m.status())
    assert GKEY not in json.dumps(run(m.describe()))
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    s = ModelSettings.from_env()
    assert (s.model, s.reasoning_effort) == ("qwen/qwen3.8-27b", None)    # Qwen: Groq's default (no reasoning)
    # a successful call logs tokens and the limits left, never the key
    backend = GroqBackend(GQ, transport=httpx.MockTransport(lambda r: ok("x")), api_key=GKEY)
    with caplog.at_level(logging.INFO, logger="afya_api.model"):
        run(Model(backend, GQ).call([], "investigate"))
    assert "tokens=900/120" in caplog.text and "tokens/min=7000" in caplog.text and GKEY not in caplog.text


def test_reset_header_durations():
    assert _duration_s("7.66s") == pytest.approx(7.66)
    assert _duration_s("2m59.56s") == pytest.approx(179.56)
    assert _duration_s("547ms") == pytest.approx(0.547)
    assert _duration_s("1h2m3s") == pytest.approx(3723)
    assert _duration_s("") is None and _duration_s("soon") is None
