"""E5-9: model settings and limits. Pure unit tests (no Postgres, no Ollama): a fake clock and fake transports."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from afya_api.model import (
    CircuitBreaker,
    Model,
    ModelSettings,
    ModelUnavailable,
    OllamaBackend,
    OpenRouterBackend,
    Reply,
    backend_for,
)


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


def test_on_close_runs_only_when_the_breaker_was_open_and_closes():
    clock = Clock()
    backend = Scripted(httpx.ConnectError("refused"), httpx.ConnectError("refused"), Reply("ok"), Reply("ok"))
    closed = []
    m = Model(backend, ModelSettings(call_timeout_s=0.05), clock=clock)

    async def on_close():
        closed.append(1)
    m.on_close = on_close
    for _ in range(2):
        with pytest.raises(ModelUnavailable):
            run(m.call([], "map_signs"))
    assert not closed
    clock.t += 301
    run(m.call([], "map_signs"))                           # half-open trial succeeds: recovery
    assert closed == [1]
    run(m.call([], "map_signs"))                           # already closed: nothing more
    assert closed == [1]


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
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    monkeypatch.setenv("MODEL", "qwen3:4b-instruct")
    monkeypatch.setenv("MODEL_SEED", "7")
    s = ModelSettings.from_env()
    assert (s.model, s.seed, s.call_timeout_s, s.run_timeout_s) == ("qwen3:4b-instruct", 7, 60.0, 240.0)
    assert run(Model(Scripted()).describe())["digest"] == "sha256:fake"


# ---------- E5-11: OpenRouter, open-weights model, pinned provider, synthetic-data guard, billed cost ----------

KEY = "sk-or-test-not-a-real-key"
OR = ModelSettings(provider="openrouter", model="qwen/qwen3-30b-a3b-instruct-2507", openrouter_url="http://or.test",
                   backoff_s=0.0)


def or_answer(content="", tool_calls=None, cost=0.000042):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"id": "gen-1", "model": "qwen/qwen3-30b-a3b-instruct-2507", "provider": "Nebius",
            "choices": [{"message": msg, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 512, "completion_tokens": 40, "cost": cost}}


def test_openrouter_request_pins_the_provider_and_reads_the_billed_cost():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=or_answer('{"verdict": "none", "signs": []}'))

    backend = OpenRouterBackend(OR, transport=httpx.MockTransport(handler), api_key=KEY)
    reply = run(backend.chat([{"role": "user", "content": "x"}], options=OR.options("map_signs", seed=7),
                             tools=None, format={"type": "object"}))
    assert seen["url"] == "http://or.test/chat/completions" and seen["auth"] == f"Bearer {KEY}"
    assert seen["model"] == "qwen/qwen3-30b-a3b-instruct-2507"
    assert seen["provider"] == {"order": ["nebius/fp8"], "allow_fallbacks": False, "require_parameters": True}
    assert (seen["temperature"], seen["top_p"], seen["top_k"], seen["seed"], seen["max_tokens"]) == (0.0, 0.8, 20, 7,
                                                                                                    384)
    assert seen["response_format"]["json_schema"]["schema"] == {"type": "object"} and "tools" not in seen
    assert seen["usage"] == {"include": True}
    assert (reply.tokens_in, reply.tokens_out, reply.cost_usd, reply.provider) == (512, 40, 0.000042, "Nebius")
    assert KEY not in repr(backend)


def test_openrouter_tool_calls_round_trip_with_ids():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        call = {"id": "c1", "type": "function", "function": {"name": "fhir_search", "arguments": '{"count": 3}'}}
        return httpx.Response(200, json=or_answer(tool_calls=[call]))

    backend = OpenRouterBackend(OR, transport=httpx.MockTransport(handler), api_key=KEY)
    history = [{"role": "system", "content": "s"},
               {"role": "assistant", "content": "", "tool_calls": [{"id": "call_0_0", "function": {
                   "name": "get_queue_state", "arguments": {}}}]},
               {"role": "tool", "content": "{}", "tool_name": "get_queue_state", "tool_call_id": "call_0_0"}]
    tools = [{"type": "function", "function": {"name": "fhir_search", "parameters": {"type": "object"}}}]
    reply = run(backend.chat(history, options=OR.options("investigate"), tools=tools, format=None))
    assert reply.tool_calls == [{"name": "fhir_search", "args": {"count": 3}}]
    sent = seen["messages"]
    assert sent[1]["tool_calls"][0] == {"id": "call_0_0", "type": "function",
                                        "function": {"name": "get_queue_state", "arguments": "{}"}}
    assert sent[2] == {"role": "tool", "tool_call_id": "call_0_0", "content": "{}"}
    assert seen["tools"] == tools and seen["tool_choice"] == "auto"


def test_remote_provider_is_refused_unless_the_data_is_synthetic():
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json=or_answer("{}")))
    real = ModelSettings(provider="openrouter", openrouter_url="http://or.test", data_classification="real")
    m = Model(OpenRouterBackend(real, transport=transport, api_key=KEY), real)
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([{"role": "user", "content": "x"}], "map_signs"))
    assert e.value.reason == "data_not_synthetic" and calls == [] and m.breaker.failures == 0
    assert m.status()["ready"] is False and m.status()["refused"] == "data_not_synthetic"
    assert run(m.warm_up()) is False and calls == []
    # the backend refuses on its own too (defence in depth), even without the Model wrapper
    with pytest.raises(ModelUnavailable):
        run(OpenRouterBackend(real, transport=transport, api_key=KEY).chat([], options=real.options("warm_up")))
    assert calls == []


def test_no_api_key_means_rules_only_without_counting_a_failure():
    m = Model(OpenRouterBackend(OR, transport=httpx.MockTransport(lambda r: httpx.Response(500)), api_key=""), OR)
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([], "map_signs"))
    assert e.value.reason == "no_api_key" and m.breaker.failures == 0 and m.breaker.state == "closed"


def test_429_and_5xx_are_retried_with_backoff_then_counted_once():
    answers = [httpx.Response(429, headers={"retry-after": "0"}), httpx.Response(502),
               httpx.Response(200, json=or_answer("ok"))]
    m = Model(OpenRouterBackend(OR, transport=httpx.MockTransport(lambda r: answers.pop(0)), api_key=KEY), OR)
    assert run(m.call([], "investigate")).content == "ok" and m.breaker.failures == 0
    always = Model(OpenRouterBackend(OR, transport=httpx.MockTransport(lambda r: httpx.Response(503)),
                                     api_key=KEY), OR)
    with pytest.raises(ModelUnavailable) as e:
        run(always.call([], "investigate"))
    assert e.value.reason == "http_error" and always.breaker.failures == 1     # 3 attempts, one failure


def test_openrouter_settings_and_the_key_is_never_in_settings(monkeypatch):
    for k in ("OPENROUTER_MODEL", "DATA_CLASSIFICATION", "MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    s = ModelSettings.from_env()
    assert (s.provider, s.model, s.openrouter_provider, s.data_classification) == (
        "openrouter", "qwen/qwen3-30b-a3b-instruct-2507", "nebius/fp8", "synthetic")
    m = Model(backend_for(s), s)
    assert KEY not in repr(s) and KEY not in json.dumps(m.status()) and KEY not in json.dumps(run(m.describe()))
    assert run(m.describe())["provider_pinned"] == "nebius/fp8"
    monkeypatch.setenv("MODEL_PROVIDER", "elsewhere")
    with pytest.raises(ValueError):
        ModelSettings.from_env()


def test_seed_varies_per_run_and_is_reproducible():
    s = ModelSettings(seed=42, seed_per_run=True)
    assert s.run_seed("v1:o1") == s.run_seed("v1:o1") != s.run_seed("v1:o2")
    assert ModelSettings(seed=42).run_seed("v1:o1") == 42


# ---------- E5-11: Ollama Cloud (native /api/chat on ollama.com, Bearer key, synthetic-data guard) ----------

OKEY = "ollama-test-not-a-real-key"
OC = ModelSettings(provider="ollama_cloud", model="gpt-oss:120b", ollama_cloud_url="http://cloud.test", think="low",
                   num_predict=1024, backoff_s=0.0)


def oc_answer(content="", tool_calls=None):
    msg = {"role": "assistant", "content": content, "thinking": "short reasoning"}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"model": "gpt-oss:120b", "message": msg, "done": True, "prompt_eval_count": 700, "eval_count": 60}


def test_ollama_cloud_sends_the_key_and_puts_the_schema_in_the_prompt():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"], seen["url"] = request.headers.get("authorization"), str(request.url)
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=oc_answer('```json\n{"verdict": "none", "signs": []}\n```'))

    backend = OllamaBackend(OC, transport=httpx.MockTransport(handler), api_key=OKEY)
    schema = {"type": "object", "properties": {"verdict": {"type": "string"}}}
    reply = run(backend.chat([{"role": "user", "content": "x"}], options=OC.options("map_signs", seed=7), tools=None,
                             format=schema))
    assert seen["url"] == "http://cloud.test/api/chat" and seen["auth"] == f"Bearer {OKEY}"
    assert seen["model"] == "gpt-oss:120b" and seen["think"] == "low" and seen["stream"] is False
    assert "format" not in seen and "keep_alive" not in seen     # cloud: no structured outputs, nothing to keep loaded
    assert seen["messages"][-1]["role"] == "system" and json.dumps(schema, separators=(",", ":")) in \
        seen["messages"][-1]["content"]
    assert seen["options"]["seed"] == 7 and seen["options"]["num_predict"] == 1024
    assert json.loads(reply.content) == {"verdict": "none", "signs": []}       # code fence removed
    assert (reply.tokens_in, reply.tokens_out, reply.provider, reply.cost_usd) == (700, 60, "ollama_cloud", None)
    assert OKEY not in repr(backend)
    sent = OllamaBackend(ModelSettings(provider="ollama_cloud", cloud_format=True, ollama_cloud_url="http://c.test"),
                         api_key=OKEY).body([], OC.options("map_signs"), None, schema)
    assert sent["format"] == schema                                            # OLLAMA_CLOUD_FORMAT=1


def test_ollama_cloud_tool_calls_use_the_native_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=oc_answer(tool_calls=[{"function": {"name": "fhir_search",
                                                                            "arguments": {"count": 3}}}]))

    tools = [{"type": "function", "function": {"name": "fhir_search", "parameters": {"type": "object"}}}]
    reply = run(OllamaBackend(OC, transport=httpx.MockTransport(handler), api_key=OKEY).chat(
        [{"role": "user", "content": "x"}], options=OC.options("investigate"), tools=tools, format=None))
    assert seen["tools"] == tools and reply.tool_calls == [{"name": "fhir_search", "args": {"count": 3}}]


def test_ollama_cloud_is_refused_without_synthetic_data_or_key():
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json=oc_answer("{}")))
    real = ModelSettings(provider="ollama_cloud", ollama_cloud_url="http://cloud.test", data_classification="real")
    m = Model(OllamaBackend(real, transport=transport, api_key=OKEY), real)
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([{"role": "user", "content": "x"}], "map_signs"))
    assert e.value.reason == "data_not_synthetic" and m.breaker.failures == 0
    assert run(m.warm_up()) is False
    with pytest.raises(ModelUnavailable):      # the backend refuses on its own too
        run(OllamaBackend(real, transport=transport, api_key=OKEY).chat([], options=real.options("warm_up")))
    nokey = Model(OllamaBackend(OC, transport=transport, api_key=""), OC)
    with pytest.raises(ModelUnavailable) as e:
        run(nokey.call([], "map_signs"))
    assert e.value.reason == "no_api_key" and nokey.breaker.failures == 0 and calls == []


def test_local_ollama_is_exempt_only_on_a_local_or_bridge_address():
    for url in ("http://host.docker.internal:11434", "http://172.17.0.1:11434", "http://127.0.0.1:11434",
                "http://localhost:11434", "http://ollama:11434", "http://192.168.1.20:11434"):
        b = OllamaBackend(ModelSettings(base_url=url, data_classification="real"))
        assert b.refusal() is None and not b.remote, url
    far = OllamaBackend(ModelSettings(base_url="https://gpu.example.org", data_classification="real"))
    assert far.remote and far.refusal() == "data_not_synthetic"
    assert OllamaBackend(ModelSettings(base_url="https://gpu.example.org")).refusal() is None   # synthetic: allowed


def test_local_ollama_never_gets_the_cloud_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", OKEY)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=oc_answer("ok"))

    run(OllamaBackend(ModelSettings(base_url="http://ollama.test"), transport=httpx.MockTransport(handler)).chat(
        [], options=ModelSettings().options("warm_up")))
    assert seen["auth"] is None


def test_ollama_cloud_limits_are_model_unavailable_and_open_the_breaker():
    m = Model(OllamaBackend(OC, transport=httpx.MockTransport(lambda r: httpx.Response(429, json={"error": "x"})),
                            api_key=OKEY), OC)
    with pytest.raises(ModelUnavailable) as e:
        run(m.call([], "map_signs"))
    assert e.value.reason == "rate_limited" and m.breaker.failures == 1
    spent = Model(OllamaBackend(OC, transport=httpx.MockTransport(lambda r: httpx.Response(402, json={"error": "x"})),
                                api_key=OKEY), OC)
    with pytest.raises(ModelUnavailable) as e:
        run(spent.call([], "map_signs"))
    assert e.value.reason == "usage_limit"
    with pytest.raises(ModelUnavailable) as e:
        run(spent.call([], "map_signs"))
    assert spent.breaker.state == "open"
    with pytest.raises(ModelUnavailable) as e:
        run(spent.call([], "map_signs"))
    assert e.value.reason == "circuit_open"
    err = Model(OllamaBackend(OC, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"error": "x"})),
                              api_key=OKEY), OC)
    with pytest.raises(ModelUnavailable) as e:
        run(err.call([], "map_signs"))
    assert e.value.reason == "invalid_response"


def test_ollama_cloud_calls_are_queued_one_at_a_time():
    active, peak = [0], [0]

    async def handler(request: httpx.Request) -> httpx.Response:
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(0.01)
        active[0] -= 1
        return httpx.Response(200, json=oc_answer("ok"))

    backend = OllamaBackend(OC, transport=httpx.MockTransport(handler), api_key=OKEY)

    async def both():
        await asyncio.gather(*(backend.chat([], options=OC.options("investigate")) for _ in range(3)))
    run(both())
    assert peak[0] == 1


def test_ollama_cloud_settings_from_env_never_hold_the_key(monkeypatch):
    for k in ("MODEL_PROVIDER", "OLLAMA_CLOUD_MODEL", "OLLAMA_CLOUD_BASE_URL", "MODEL_THINK", "MODEL_NUM_PREDICT",
              "OLLAMA_CLOUD_FORMAT", "DATA_CLASSIFICATION"):
        monkeypatch.delenv(k, raising=False)            # the default provider is Ollama Cloud
    monkeypatch.setenv("OLLAMA_API_KEY", OKEY)
    s = ModelSettings.from_env()
    assert (s.provider, s.model, s.ollama_cloud_url, s.think, s.num_predict, s.cloud_format) == (
        "ollama_cloud", "gpt-oss:120b", "https://ollama.com", "low", 1024, False)
    m = Model(backend_for(s), s)
    assert m.status()["provider"] == "ollama_cloud" and m.status()["refused"] is None
    assert OKEY not in repr(s) and OKEY not in repr(m.backend) and OKEY not in json.dumps(m.status())
    monkeypatch.setenv("OLLAMA_CLOUD_MODEL", "qwen3-next:80b")
    monkeypatch.setenv("MODEL_THINK", "false")
    s = ModelSettings.from_env()
    assert (s.model, s.think) == ("qwen3-next:80b", False)


def test_a_limit_during_warm_up_is_recorded_for_healthz_and_the_eval_runner():
    m = Model(OllamaBackend(OC, transport=httpx.MockTransport(lambda r: httpx.Response(402)), api_key=OKEY), OC)
    assert run(m.warm_up()) is False and m.last == "usage_limit" and m.breaker.failures == 0
