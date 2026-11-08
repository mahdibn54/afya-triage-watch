"""E5-9 / E5-11: the language model client, its settings and its limits (architecture section 8).

Four transports, picked with `MODEL_PROVIDER` (the model of each provider comes from its own variable):
- `openrouter`: an OPEN-WEIGHTS Qwen3 model through OpenRouter's chat completions API, with the provider
  pinned (`provider.order`, `allow_fallbacks: false`, `require_parameters: true`) and the billed `usage.cost` read
  from every answer. It is a remote service, so it is used ONLY when `DATA_CLASSIFICATION=synthetic` (the default of
  this prototype, which holds synthetic patients only). Any other value, or no `OPENROUTER_API_KEY`, refuses the call:
  the agent goes on with the fixed rules and the card says `model_unavailable`. A real deployment runs the same
  open-weights model hosted in-country (`MODEL_PROVIDER=ollama` or another local server).
- `ollama_cloud` (default, Mahdi's decision): Ollama's own hosted API (https://ollama.com/api,
  `Authorization: Bearer $OLLAMA_API_KEY`), the same native /api/chat as a local Ollama, with an open-weights
  model chosen by the name `GET /api/tags` returns (default `gpt-oss:120b`). Remote, so the same synthetic-data
  guard as OpenRouter applies; no key also refuses the call. Ollama documents that its cloud does not support
  structured outputs, so by default the JSON schema goes into the prompt (and the answer is still validated by the
  caller, with one retry); `OLLAMA_CLOUD_FORMAT=1` sends `format` instead.
  At most `OLLAMA_CLOUD_CONCURRENCY` (default 1) calls at a time; HTTP 429 ends as `rate_limited` and 402 as
  `usage_limit` (the plan's limit), both counted by the breaker so the agent backs off and runs on the rules.
- `groq`: GroqCloud's OpenAI-compatible chat completions (https://api.groq.com/openai/v1, `Authorization: Bearer
  $GROQ_API_KEY`) with an open-weights model (`GROQ_MODEL`, e.g. `openai/gpt-oss-120b`, Apache-2.0). Same code path
  as OpenRouter (message shape, tool ids, `response_format` json_schema with `strict: true`) without OpenRouter's own
  fields (provider pinning, `usage.include`, `top_k`, which Groq rejects with HTTP 400). Same synthetic-data guard.
  The free plan has small limits (gpt-oss-120b: 30 requests/min, 1K requests/day, 8K tokens/min, 200K tokens/day),
  so the backend paces itself from Groq's `x-ratelimit-*` headers (tokens per minute, requests per day), sends at
  most `GROQ_CONCURRENCY` (default 1) calls at a time, honours `retry-after` on 429 only when the wait fits in the
  call's time, and otherwise ends as `rate_limited` (or `daily_limit` when Groq says the per-day limit is spent),
  counted by the breaker: the agent backs off and still proposes from the rules. Cost on the free plan is 0; tokens
  and seconds are logged per call.
- `ollama`: Ollama's /api/chat with `think: false` set explicitly (qwen3 would otherwise think). Exempt from the
  synthetic-data guard only while `OLLAMA_BASE_URL` is a local or private (bridge) address; any other host is remote.

All get the same sampling settings and a seed that is logged with each call (the seed varies per run, derived from
the run id, so repeated runs are independent samples yet reproducible; `MODEL_SEED_PER_RUN=0` keeps it fixed).
Limits: 60 s per call, 240 s per run (the caller passes the run's deadline), one retry on invalid JSON with the error
included, HTTP 429/5xx retried with backoff inside the call's time, and a circuit breaker that skips the model for
5 minutes after 2 failures in a row and then lets exactly ONE trial call through. A failure of any kind (timeout,
HTTP error, an answer that is not what the API promises, an exception in the transport) raises `ModelUnavailable`;
the agent then goes on with the fixed rules only (E5-10). Nothing here decides anything clinical.

The API key is read from the environment by the backend and only ever sent in the Authorization header: it is never
part of the settings, a log line, the trace or an error message.
"""
from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import json
import logging
import os
import re
import time
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

log = logging.getLogger("afya_api.model")

PURPOSES = ("map_signs", "investigate", "warm_up")
PROVIDERS = ("openrouter", "ollama", "ollama_cloud", "groq")
# E5-11: chosen from https://openrouter.ai/api/v1/models (Decisions log): Qwen3-30B-A3B-Instruct-2507, Apache-2.0
# open weights, non-thinking, tools + structured outputs + seed + top_k on the pinned provider.
OPENROUTER_MODEL = "qwen/qwen3-30b-a3b-instruct-2507"
OPENROUTER_PROVIDER = "nebius/fp8"
OLLAMA_MODEL = "qwen3:8b"
# Ollama Cloud: endpoint and auth from docs.ollama.com/cloud and /api/authentication; model names from GET /api/tags.
# gpt-oss:120b is Apache-2.0 open weights with tool calling; no Qwen3 is in the cloud list (Decisions log).
OLLAMA_CLOUD_URL = "https://ollama.com"
OLLAMA_CLOUD_MODEL = "gpt-oss:120b"
# Groq (console.groq.com/docs/openai, /docs/rate-limits): gpt-oss-120b is Apache-2.0 open weights with tool calling and
# strict JSON schema output; qwen/qwen3.8-27b (Apache-2.0 on Hugging Face, a "preview" model on Groq) is the backup.
GROQ_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-120b"
SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class ModelSettings:
    provider: str = "ollama"
    base_url: str = "http://host.docker.internal:11434"
    model: str = OLLAMA_MODEL
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_provider: str = OPENROUTER_PROVIDER
    ollama_cloud_url: str = OLLAMA_CLOUD_URL
    cloud_format: bool = False      # Ollama Cloud: send `format` (documented as unsupported) instead of the prompt
    cloud_concurrency: int = 1
    groq_url: str = GROQ_URL
    groq_concurrency: int = 1
    reasoning_effort: str | None = None   # Groq `reasoning_effort` ("low" for gpt-oss); None = not sent
    think: bool | str = False       # Ollama `think`: false, or a level such as "low" for gpt-oss (cannot switch off)
    data_classification: str = SYNTHETIC
    num_ctx: int = 8192
    num_predict: int = 384
    top_p: float = 0.8
    top_k: int = 20
    seed: int = 42
    seed_per_run: bool = False
    keep_alive: str | int = "30m"
    call_timeout_s: float = 60.0
    run_timeout_s: float = 240.0
    breaker_failures: int = 2
    breaker_cooldown_s: float = 300.0
    http_retries: int = 2           # 429 / 5xx: retried with backoff while the call's time allows
    backoff_s: float = 1.0
    backoff_cap_s: float = 8.0
    temperatures: dict[str, float] = field(default_factory=lambda: {"map_signs": 0.0, "investigate": 0.2,
                                                                    "warm_up": 0.0})

    @classmethod
    def from_env(cls) -> ModelSettings:
        env = os.environ.get
        provider = env("MODEL_PROVIDER", "ollama_cloud").strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(f"MODEL_PROVIDER must be one of {PROVIDERS}")
        model = {"openrouter": lambda: env("OPENROUTER_MODEL", OPENROUTER_MODEL),
                 "groq": lambda: env("GROQ_MODEL", GROQ_MODEL),
                 "ollama_cloud": lambda: env("OLLAMA_CLOUD_MODEL", OLLAMA_CLOUD_MODEL)}.get(
                     provider, lambda: env("MODEL", OLLAMA_MODEL))()
        keep: str | int = env("MODEL_KEEP_ALIVE", "30m")
        if isinstance(keep, str) and keep.lstrip("-").isdigit():
            keep = int(keep)          # Ollama: a number is seconds, -1 keeps the model loaded
        # gpt-oss cannot switch thinking off; "low" keeps its reasoning short. Its reasoning tokens count against
        # num_predict, so the cloud default leaves more room (both overridable).
        think_default = "low" if provider == "ollama_cloud" and model.startswith("gpt-oss") else "false"
        think_raw = env("MODEL_THINK", think_default).strip().lower()
        think: bool | str = {"false": False, "true": True}.get(think_raw, think_raw)
        # Groq: gpt-oss reasons always, "low" keeps it short. MODEL_REASONING_EFFORT overrides (empty = this default,
        # "off" = not sent; Groq's own values such as "none" are sent as they are).
        effort_default = "low" if provider == "groq" and "gpt-oss" in model else "off"
        effort_raw = (env("MODEL_REASONING_EFFORT") or effort_default).strip().lower()
        effort = None if effort_raw == "off" else effort_raw
        predict_default = 1024 if provider in ("ollama_cloud", "groq") else cls.num_predict
        return cls(provider=provider, base_url=env("OLLAMA_BASE_URL", cls.base_url), model=model,
                   openrouter_url=env("OPENROUTER_BASE_URL", cls.openrouter_url),
                   openrouter_provider=env("OPENROUTER_PROVIDER", OPENROUTER_PROVIDER),
                   ollama_cloud_url=env("OLLAMA_CLOUD_BASE_URL", OLLAMA_CLOUD_URL).rstrip("/"),
                   cloud_format=env("OLLAMA_CLOUD_FORMAT", "0") == "1",
                   cloud_concurrency=max(1, int(env("OLLAMA_CLOUD_CONCURRENCY", "1"))), think=think,
                   groq_url=(env("GROQ_BASE_URL") or GROQ_URL).rstrip("/"),
                   groq_concurrency=max(1, int(env("GROQ_CONCURRENCY", "1"))), reasoning_effort=effort,
                   num_predict=int(env("MODEL_NUM_PREDICT", str(predict_default))),
                   data_classification=env("DATA_CLASSIFICATION", SYNTHETIC).strip().lower(),
                   seed=int(env("MODEL_SEED", str(cls.seed))), seed_per_run=env("MODEL_SEED_PER_RUN", "1") != "0",
                   keep_alive=keep,
                   call_timeout_s=float(env("MODEL_CALL_TIMEOUT_SECONDS", str(cls.call_timeout_s))),
                   run_timeout_s=float(env("RUN_TIMEOUT_SECONDS", str(cls.run_timeout_s))))

    def run_seed(self, run_id: str | None) -> int:
        """The seed of one run: fixed MODEL_SEED, or (default) MODEL_SEED + crc32(run id), logged with each call."""
        if not self.seed_per_run or not run_id:
            return self.seed
        return (self.seed + zlib.crc32(run_id.encode())) % 2_147_483_647

    def options(self, purpose: str, seed: int | None = None) -> dict[str, Any]:
        return {"num_ctx": self.num_ctx, "num_predict": 1 if purpose == "warm_up" else self.num_predict,
                "temperature": self.temperatures[purpose], "top_p": self.top_p, "top_k": self.top_k,
                "seed": self.seed if seed is None else seed}


@dataclass
class Reply:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)   # [{"name": ..., "args": {...}}]
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: float | None = None
    load_ms: float | None = None
    eval_ms: float | None = None
    model: str | None = None
    cost_usd: float | None = None      # billed cost (OpenRouter usage.cost); 0 for a local model and Groq's free plan
    provider: str | None = None        # who served it (OpenRouter's answer); None for a local model


class ModelUnavailable(Exception):
    """The model was not used: reason is one of circuit_open, run_budget, timeout, warming_up, unreachable,
    http_error, rate_limited, daily_limit, usage_limit, invalid_response, invalid_output, disabled, data_not_synthetic,
    no_api_key."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProviderLimit(Exception):
    """The provider's own limit, seen before or instead of an HTTP error (Groq pacing): `rate_limited` or
    `daily_limit`. Counted by the breaker like a 429."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Model.call sets the monotonic time by which the backend must have answered, so a backend can decide whether a
# provider's wait (retry-after, rate-limit reset) still fits in the call instead of being cut off by the timeout.
CALL_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar("model_call_deadline", default=None)


class Backend(Protocol):
    async def chat(self, messages: list[dict[str, Any]], *, options: dict[str, Any],
                   tools: list[dict[str, Any]] | None, format: dict[str, Any] | None) -> Reply: ...

    async def digest(self) -> str | None: ...


async def _post_with_retry(client: httpx.AsyncClient, path: str, body: dict[str, Any], s: ModelSettings,
                           headers: dict[str, str] | None = None,
                           sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                           on_response: Callable[[httpx.Response], None] | None = None,
                           honour_retry_after: bool = False) -> httpx.Response:
    """POST; on 429 or 5xx wait (Retry-After if given, else exponential) and try again, at most `http_retries`
    times. The caller's asyncio timeout bounds the whole thing. The last answer is raised as HTTPStatusError.
    `honour_retry_after` (Groq): wait the full Retry-After when it fits before the call's deadline (CALL_DEADLINE),
    otherwise give up at once; a per-day limit is never retried."""
    for attempt in range(s.http_retries + 1):
        r = await client.post(path, json=body, headers=headers)
        if on_response is not None:
            on_response(r)
        if (r.status_code == 429 or r.status_code >= 500) and attempt < s.http_retries:
            try:
                wait = float(r.headers.get("retry-after", ""))
            except ValueError:
                wait = s.backoff_s * 2 ** attempt
            if honour_retry_after:
                deadline = CALL_DEADLINE.get()
                if _limit_kind(r) == "daily_limit" or (
                        deadline is not None and time.monotonic() + max(wait, 0.0) + 2.0 > deadline):
                    r.raise_for_status()
                wait = max(wait, 0.0)
            else:
                wait = min(max(wait, 0.0), s.backoff_cap_s)
            log.warning("model HTTP %s, retry %d in %.1fs", r.status_code, attempt + 1, wait)
            await sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise AssertionError("unreachable")


def is_local_url(url: str) -> bool:
    """True for loopback, private (RFC 1918, Docker bridge) and link-local addresses and the names a compose stack
    uses for the host or a sibling container; anything else is a remote service."""
    host = (httpx.URL(url).host or "").lower()
    if host in ("localhost", "host.docker.internal", "ollama") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


class OllamaBackend:
    """Ollama native /api/chat, non-streaming, `think` sent explicitly (false; a level for gpt-oss). One class for
    the local server (`ollama`) and Ollama's hosted API (`ollama_cloud`, Bearer key, synthetic-data guard)."""

    def __init__(self, settings: ModelSettings, transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic, api_key: str | None = None) -> None:
        self.s, self.transport, self.clock = settings, transport, clock   # transport: tests (httpx.MockTransport)
        self.cloud = settings.provider == "ollama_cloud"
        self.url = settings.ollama_cloud_url if self.cloud else settings.base_url
        self.remote = self.cloud or not is_local_url(self.url)
        key = api_key if api_key is not None else os.environ.get("OLLAMA_API_KEY", "")
        self._key = key.strip() if self.cloud else ""   # the key goes to ollama.com only, never to a local server
        self._digest: str | None = None
        self._digest_failed_at: float | None = None
        self._slots: asyncio.Semaphore | None = None

    def __repr__(self) -> str:   # never show the key
        return f"OllamaBackend(provider={self.s.provider!r}, model={self.s.model!r}, remote={self.remote})"

    def refusal(self) -> str | None:
        """Why this server may not be called now (None = it may). A local/bridge server: no data leaves the
        machine, always allowed. Ollama Cloud or any other remote host: synthetic data only; the cloud needs a key."""
        if not self.remote:
            return None
        if self.s.data_classification != SYNTHETIC:
            return "data_not_synthetic"
        if self.cloud and not self._key:
            return "no_api_key"
        return None

    def info(self) -> dict[str, Any]:
        if self.cloud:
            return {"provider": "ollama_cloud", "data_classification": self.s.data_classification}
        out: dict[str, Any] = {"provider": "ollama", "keep_alive": self.s.keep_alive}
        if self.remote:
            out["data_classification"] = self.s.data_classification
        return out

    def _headers(self) -> dict[str, str] | None:
        return {"Authorization": f"Bearer {self._key}"} if self._key else None

    def body(self, messages: list[dict[str, Any]], options: dict[str, Any], tools: list[dict[str, Any]] | None,
             format: dict[str, Any] | None) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.s.model, "messages": messages, "stream": False, "think": self.s.think,
                                "options": options}
        if not self.cloud:
            body["keep_alive"] = self.s.keep_alive   # a hosted model is not ours to keep loaded
        if tools:
            body["tools"] = tools
        if format is not None:
            if self.cloud and not self.s.cloud_format:
                # Ollama Cloud does not support structured outputs (docs.ollama.com/capabilities/structured-outputs):
                # the schema goes into the prompt, as those docs advise; the caller still validates the answer.
                body["messages"] = [*messages, {"role": "system", "content":
                                                "Answer with one JSON object only, no other text, that matches this "
                                                "JSON schema exactly:\n" + json.dumps(format, separators=(",", ":"))}]
            else:
                body["format"] = format
        return body

    async def chat(self, messages: list[dict[str, Any]], *, options: dict[str, Any],
                   tools: list[dict[str, Any]] | None = None, format: dict[str, Any] | None = None) -> Reply:
        why = self.refusal()
        if why:
            raise ModelUnavailable(why)
        body = self.body(messages, options, tools, format)
        if self.cloud:
            if self._slots is None:
                self._slots = asyncio.Semaphore(self.s.cloud_concurrency)
            async with self._slots:      # the plan allows few concurrent requests: queue here, not at the provider
                return await self._send(body, format is not None)
        return await self._send(body, False)

    async def _send(self, body: dict[str, Any], unfence: bool) -> Reply:
        start = time.perf_counter()
        async with httpx.AsyncClient(base_url=self.url, timeout=None, transport=self.transport) as client:
            r = await _post_with_retry(client, "/api/chat", body, self.s, headers=self._headers())
        d = r.json()
        if not isinstance(d, dict) or d.get("error"):
            raise ValueError("provider error")         # never echo the provider's text (could quote the request)
        msg = d.get("message") or {}
        calls = []
        for c in msg.get("tool_calls") or []:
            fn = c.get("function") or {}
            calls.append({"name": str(fn.get("name", "")), "args": _args(fn.get("arguments"))})
        content = msg.get("content") or ""
        if unfence and self.cloud:
            m = _FENCE.match(content)
            content = m.group(1) if m else content
        ns = 1e6
        return Reply(content=content, tool_calls=calls, tokens_in=d.get("prompt_eval_count"),
                     tokens_out=d.get("eval_count"), latency_ms=round((time.perf_counter() - start) * 1000, 1),
                     load_ms=round(d["load_duration"] / ns, 1) if d.get("load_duration") else None,
                     eval_ms=round(d["eval_duration"] / ns, 1) if d.get("eval_duration") else None,
                     model=d.get("model", self.s.model), cost_usd=None if self.cloud else 0.0,
                     provider="ollama_cloud" if self.cloud else None)

    async def digest(self) -> str | None:
        """The model's digest from /api/tags (logged with every call). Cached; while the server is unreachable the
        failure is cached for 60 s too, so a down server does not cost a 5 s wait on every step."""
        if self._digest is None:
            if self._digest_failed_at is not None and self.clock() - self._digest_failed_at < 60:
                return None
            try:
                async with httpx.AsyncClient(base_url=self.url, timeout=5, transport=self.transport) as client:
                    tags = (await client.get("/api/tags", headers=self._headers())).json().get("models", [])
                self._digest = next((m.get("digest") for m in tags if m.get("name") == self.s.model
                                     or m.get("model") == self.s.model), None)
            except Exception:  # noqa: BLE001 - the digest is information only
                self._digest_failed_at = self.clock()
                return None
        return self._digest


def _args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {"_unparsed": True}
    return raw if isinstance(raw, dict) else {}


def to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Our messages (Ollama shape) -> OpenAI chat shape: tool-call arguments as JSON text, with ids that the tool
    answers refer to."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            calls = [{"id": c.get("id") or f"call_{len(out)}_{i}", "type": "function",
                      "function": {"name": c["function"]["name"],
                                   "arguments": json.dumps(c["function"].get("arguments") or {})}}
                     for i, c in enumerate(m["tool_calls"])]
            out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": calls})
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id") or "", "content": m.get("content", "")})
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


def openai_reply(d: Any, model: str, start: float) -> Reply:
    """An OpenAI-shaped chat completion -> Reply (content, tool calls, token counts, latency). A provider error body
    or an answer without choices raises ValueError (never with the provider's text)."""
    if not isinstance(d, dict) or d.get("error") or not d.get("choices"):
        code = (d.get("error") or {}).get("code") if isinstance(d, dict) else None
        raise ValueError(f"provider error {code}" if code else "no choices in the answer")
    msg = d["choices"][0].get("message") or {}
    calls = [{"name": str((c.get("function") or {}).get("name", "")),
              "args": _args((c.get("function") or {}).get("arguments"))} for c in msg.get("tool_calls") or []]
    usage = d.get("usage") or {}
    return Reply(content=msg.get("content") or "", tool_calls=calls, tokens_in=usage.get("prompt_tokens"),
                 tokens_out=usage.get("completion_tokens"),
                 latency_ms=round((time.perf_counter() - start) * 1000, 1), model=d.get("model", model))


def json_schema_format(schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": "answer", "strict": True, "schema": schema}}


class OpenRouterBackend:
    """OpenRouter /chat/completions, non-streaming, provider pinned, billed cost read from `usage.cost`.
    Refuses to send anything unless DATA_CLASSIFICATION is `synthetic` (checked here AND by Model.call)."""

    def __init__(self, settings: ModelSettings, transport: httpx.AsyncBaseTransport | None = None,
                 api_key: str | None = None) -> None:
        self.s, self.transport = settings, transport
        self._key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "").strip()

    def __repr__(self) -> str:   # never show the key
        return f"OpenRouterBackend(model={self.s.model!r}, provider={self.s.openrouter_provider!r})"

    def refusal(self) -> str | None:
        """Why the remote provider may not be called now (None = it may)."""
        if self.s.data_classification != SYNTHETIC:
            return "data_not_synthetic"
        if not self._key:
            return "no_api_key"
        return None

    def info(self) -> dict[str, Any]:
        return {"provider": "openrouter", "provider_pinned": self.s.openrouter_provider,
                "data_classification": self.s.data_classification}

    def body(self, messages: list[dict[str, Any]], options: dict[str, Any], tools: list[dict[str, Any]] | None,
             format: dict[str, Any] | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.s.model, "messages": to_openai(messages), "stream": False,
            "temperature": options["temperature"], "top_p": options["top_p"], "top_k": options["top_k"],
            "seed": options["seed"], "max_tokens": options["num_predict"],
            "provider": {"order": [self.s.openrouter_provider], "allow_fallbacks": False,
                         "require_parameters": True},
            "usage": {"include": True}}
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        if format is not None:
            body["response_format"] = json_schema_format(format)
        return body

    async def chat(self, messages: list[dict[str, Any]], *, options: dict[str, Any],
                   tools: list[dict[str, Any]] | None = None, format: dict[str, Any] | None = None) -> Reply:
        why = self.refusal()
        if why:
            raise ModelUnavailable(why)
        headers = {"Authorization": f"Bearer {self._key}", "X-Title": "Afya Triage Watch"}
        start = time.perf_counter()
        async with httpx.AsyncClient(base_url=self.s.openrouter_url, timeout=None, transport=self.transport) as c:
            r = await _post_with_retry(c, "/chat/completions", self.body(messages, options, tools, format), self.s,
                                       headers=headers)
        d = r.json()
        reply = openai_reply(d, self.s.model, start)
        cost = (d.get("usage") or {}).get("cost")
        reply.cost_usd = float(cost) if isinstance(cost, (int, float)) else None
        reply.provider = d.get("provider")
        return reply

    async def digest(self) -> str | None:
        return None   # a hosted model has no digest; the model id and the serving provider are logged instead


def _duration_s(text: str | None) -> float | None:
    """Groq's reset headers: "7.66s", "2m59.56s", "547ms", "1h2m3s" -> seconds."""
    if not text:
        return None
    total, found = 0.0, False
    for num, unit in re.findall(r"([0-9]*\.?[0-9]+)(ms|h|m|s)", text):
        total += float(num) * {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[unit]
        found = True
    return total if found else None


@dataclass
class RateState:
    """What Groq's last answer said about the limits (x-ratelimit-* headers): tokens per minute and requests per
    day. Shared by every GroqBackend of the process for one base URL (the eval runner makes one backend per trial)."""
    tokens_limit: int | None = None
    tokens_left: int | None = None
    tokens_reset_at: float = 0.0
    requests_left: int | None = None
    requests_reset_at: float = 0.0

    def update(self, r: httpx.Response, now: float) -> None:
        h = r.headers

        def num(name: str) -> int | None:
            try:
                return int(float(h[name]))
            except (KeyError, ValueError):
                return None
        if num("x-ratelimit-limit-tokens") is not None:
            self.tokens_limit = num("x-ratelimit-limit-tokens")
        if num("x-ratelimit-remaining-tokens") is not None:
            self.tokens_left = num("x-ratelimit-remaining-tokens")
            self.tokens_reset_at = now + (_duration_s(h.get("x-ratelimit-reset-tokens")) or 60.0)
        if num("x-ratelimit-remaining-requests") is not None:
            self.requests_left = num("x-ratelimit-remaining-requests")
            self.requests_reset_at = now + (_duration_s(h.get("x-ratelimit-reset-requests")) or 60.0)
        if r.status_code == 429 and _limit_kind(r) == "rate_limited":
            self.tokens_left = 0
            try:
                self.tokens_reset_at = max(self.tokens_reset_at, now + float(h.get("retry-after", "")))
            except ValueError:
                pass

    def wait_for(self, tokens: int, now: float) -> float:
        """Seconds to wait before a request of about `tokens` (prompt + max output) fits the per-minute budget.
        Groq refills the bucket continuously, so the wait is the missing share of a minute, at most the reset."""
        if self.tokens_left is None or now >= self.tokens_reset_at or tokens <= self.tokens_left:
            return 0.0
        rate = (self.tokens_limit or 0) / 60.0
        missing = (tokens - self.tokens_left) / rate if rate > 0 else self.tokens_reset_at - now
        return max(0.0, min(missing, self.tokens_reset_at - now))


_GROQ_RATES: dict[str, RateState] = {}


class GroqBackend:
    """GroqCloud's OpenAI-compatible /chat/completions, non-streaming, open-weights model, strict JSON schema output.
    Remote: synthetic data only and a key (`GROQ_API_KEY`, sent only in the Authorization header). Paces itself to
    the free plan's per-minute token budget, one call at a time by default; cost is 0 on the free plan."""

    def __init__(self, settings: ModelSettings, transport: httpx.AsyncBaseTransport | None = None,
                 api_key: str | None = None, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.s, self.transport, self.sleep, self.clock = settings, transport, sleep, clock
        self._key = (api_key if api_key is not None else os.environ.get("GROQ_API_KEY", "")).strip()
        self._slots: asyncio.Semaphore | None = None
        self.rates = _GROQ_RATES.setdefault(settings.groq_url, RateState())

    def __repr__(self) -> str:   # never show the key
        return f"GroqBackend(model={self.s.model!r})"

    def refusal(self) -> str | None:
        """Why the remote provider may not be called now (None = it may)."""
        if self.s.data_classification != SYNTHETIC:
            return "data_not_synthetic"
        if not self._key:
            return "no_api_key"
        return None

    def info(self) -> dict[str, Any]:
        out: dict[str, Any] = {"provider": "groq", "data_classification": self.s.data_classification}
        if self.s.reasoning_effort:
            out["reasoning_effort"] = self.s.reasoning_effort
        return out

    def body(self, messages: list[dict[str, Any]], options: dict[str, Any], tools: list[dict[str, Any]] | None,
             format: dict[str, Any] | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.s.model, "messages": to_openai(messages), "stream": False,
            "temperature": options["temperature"], "top_p": options["top_p"], "seed": options["seed"],
            "max_completion_tokens": options["num_predict"]}     # no top_k: Groq answers 400 to it
        if self.s.reasoning_effort:
            body["reasoning_effort"] = self.s.reasoning_effort
            body["include_reasoning"] = False                  # the reasoning text is not used, not kept
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        if format is not None:
            body["response_format"] = json_schema_format(format)
        return body

    async def chat(self, messages: list[dict[str, Any]], *, options: dict[str, Any],
                   tools: list[dict[str, Any]] | None = None, format: dict[str, Any] | None = None) -> Reply:
        why = self.refusal()
        if why:
            raise ModelUnavailable(why)
        body = self.body(messages, options, tools, format)
        if self._slots is None:
            self._slots = asyncio.Semaphore(self.s.groq_concurrency)
        async with self._slots:     # the free plan's 8K tokens/min: queue here, not at the provider
            await self._pace(body)
            return await self._send(body)

    async def _pace(self, body: dict[str, Any]) -> None:
        now = self.clock()
        if self.rates.requests_left == 0 and now < self.rates.requests_reset_at:
            raise ProviderLimit("daily_limit")
        # rough size: ~3.5 characters per token of the request, plus the output Groq reserves for it
        need = int(len(json.dumps(body, separators=(",", ":"))) / 3.5) + int(body.get("max_completion_tokens") or 0)
        wait = self.rates.wait_for(need, now)
        if wait <= 0:
            return
        deadline = CALL_DEADLINE.get()
        if deadline is not None and time.monotonic() + wait + 2.0 > deadline:
            raise ProviderLimit("rate_limited")      # the per-minute budget does not refill within this call
        log.info("groq: waiting %.1fs for the tokens-per-minute budget (about %d tokens needed)", wait, need)
        await self.sleep(wait)

    async def _send(self, body: dict[str, Any]) -> Reply:
        start = time.perf_counter()
        headers = {"Authorization": f"Bearer {self._key}"}
        async with httpx.AsyncClient(base_url=self.s.groq_url, timeout=None, transport=self.transport) as c:
            for attempt in range(2):
                try:
                    r = await _post_with_retry(c, "/chat/completions", body, self.s, headers=headers,
                                               sleep=self.sleep,
                                               on_response=lambda resp: self.rates.update(resp, self.clock()),
                                               honour_retry_after=True)
                    break
                except httpx.HTTPStatusError as e:
                    code = _error_code(e.response)
                    log.warning("groq HTTP %s (%s)", e.response.status_code, code or "no code")
                    # E12-5: Groq answers 400 `tool_use_failed` when the model's own tool call did not parse or named
                    # a tool that was not offered (gpt-oss sometimes calls its "commentary" channel): a bad sample, not
                    # a bad request. One new sample (next seed) with a fixed reminder, then give up.
                    if attempt == 0 and e.response.status_code == 400 and code == "tool_use_failed":
                        body = {**body, "seed": int(body.get("seed") or 0) + 1,
                                "messages": [*body["messages"], {"role": "user", "content": TOOL_REMINDER}]}
                        continue
                    raise
        reply = openai_reply(r.json(), self.s.model, start)
        reply.cost_usd, reply.provider = 0.0, "groq"      # free plan: nothing billed
        log.info("groq limits left: tokens/min=%s requests/day=%s", self.rates.tokens_left, self.rates.requests_left)
        return reply

    async def digest(self) -> str | None:
        return None   # a hosted model has no digest; the model id is logged instead


def backend_for(settings: ModelSettings, transport: httpx.AsyncBaseTransport | None = None) -> Backend:
    if settings.provider == "openrouter":
        return OpenRouterBackend(settings, transport)
    if settings.provider == "groq":
        return GroqBackend(settings, transport)
    return OllamaBackend(settings, transport)


_DAILY = re.compile(r"per day|\((?:TPD|RPD)\)", re.I)


def _limit_kind(r: httpx.Response) -> str:
    """429 -> `daily_limit` when the provider says a per-day limit is spent (Groq: "... tokens per day (TPD) ..."),
    else `rate_limited`. Only the error's class is kept, never its text."""
    try:
        msg = str(((r.json() or {}).get("error") or {}).get("message", ""))
    except Exception:  # noqa: BLE001 - not JSON: a plain rate limit
        msg = ""
    return "daily_limit" if _DAILY.search(msg) else "rate_limited"


TOOL_REMINDER = "Your last answer did not call an offered tool. Call one of the offered tools by its exact name."


def _error_code(r: httpx.Response) -> str | None:
    """The provider's machine error code (e.g. `tool_use_failed`), never its message text."""
    try:
        code = ((r.json() or {}).get("error") or {}).get("code")
    except Exception:  # noqa: BLE001
        return None
    return code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,40}", code) else None


def status_reason(e: httpx.HTTPStatusError) -> str:
    """429: rate or concurrency limit (`daily_limit` for a per-day limit); 402: the plan's usage limit is spent;
    anything else: http_error."""
    if e.response.status_code == 429:
        return _limit_kind(e.response)
    return {402: "usage_limit"}.get(e.response.status_code, "http_error")


class CircuitBreaker:
    """Skip the model for `cooldown` seconds after `limit` failures in a row. One success resets the count. When the
    cooldown is over, exactly ONE trial call goes through (half-open); the others are still refused until it ends:
    success closes the breaker, failure opens it for another cooldown."""

    def __init__(self, limit: int = 2, cooldown: float = 300.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.cooldown, self.clock = limit, cooldown, clock
        self.failures = 0
        self.open_until: float | None = None
        self.trial = False      # a half-open trial call is in flight

    @property
    def state(self) -> str:
        if self.open_until is None:
            return "closed"
        return "half_open" if self.trial or self.clock() >= self.open_until else "open"

    def allow(self) -> bool:
        if self.open_until is None:
            return True
        if self.trial or self.clock() < self.open_until:
            return False
        self.trial = True       # this caller is the single trial
        return True

    def success(self) -> bool:
        """Reset the count and close the breaker; True when it had been open (or half-open) until now."""
        was_open = self.open_until is not None
        self.failures, self.open_until, self.trial = 0, None, False
        return was_open

    def release(self) -> None:
        """The trial ended without telling anything about the model (cancelled, run budget): next caller tries."""
        self.trial = False

    def failure(self) -> bool:
        """Count a failure; True when this failure (re)opens the breaker."""
        if self.trial:
            self.trial, self.open_until = False, self.clock() + self.cooldown
            return True
        self.failures += 1
        if self.failures >= self.limit and self.open_until is None:
            self.open_until = self.clock() + self.cooldown
            return True
        return False


@dataclass
class Call:
    """One model call as the trace logs it (IDs, codes and numbers only)."""
    purpose: str
    reply: Reply | None
    retried: bool
    error: str | None = None


class Model:
    """The guarded model: data guard, limits, breaker, retry on invalid JSON. `on_open` runs when the breaker opens
    (E5-10 sends a model_unavailable notice from it)."""

    def __init__(self, backend: Backend, settings: ModelSettings | None = None,
                 breaker: CircuitBreaker | None = None, clock: Callable[[], float] = time.monotonic,
                 enabled: bool = True) -> None:
        self.backend, self.s, self.clock, self.enabled = backend, settings or ModelSettings(), clock, enabled
        self.breaker = breaker or CircuitBreaker(self.s.breaker_failures, self.s.breaker_cooldown_s, clock)
        self.on_open: Callable[[str], Awaitable[None]] | None = None
        self.on_close: Callable[[], Awaitable[None]] | None = None   # the breaker closed again, or the warm-up worked
        self.warming = False          # a warm-up call is loading the model: timeouts meanwhile are not counted
        self.warmed: bool | None = None
        self.last: str | None = None  # "ok" or the reason of the last failure (readiness in /healthz)

    def deadline(self) -> float:
        """Run budget: a run starts here and may use the model until this clock value (240 s)."""
        return self.clock() + self.s.run_timeout_s

    def refusal(self) -> str | None:
        """Why the model may not be called at all (switched off, remote provider without synthetic data or key)."""
        if not self.enabled:
            return "disabled"
        check = getattr(self.backend, "refusal", None)
        return check() if check else None

    def status(self) -> dict[str, Any]:
        """Readiness for /healthz: ready = may be called, breaker closed, and the last call (or the warm-up)
        worked. Never contains the key."""
        refused = self.refusal()
        state = self.breaker.state
        ok = self.last == "ok" or (self.last is None and self.warmed is True)
        info = getattr(self.backend, "info", None)
        return {"provider": (info() if info else {}).get("provider", "custom"), "model": self.s.model,
                "ready": refused is None and state == "closed" and ok, "refused": refused, "breaker": state,
                "warmed_up": self.warmed, "last": self.last}

    async def describe(self, seed: int | None = None) -> dict[str, Any]:
        """Model tag, digest and settings, logged with each call (architecture section 8, 'logged per call')."""
        info = getattr(self.backend, "info", None)
        return {"tag": self.s.model, "digest": await self.backend.digest(),
                "seed": self.s.seed if seed is None else seed, "think": self.s.think, "num_ctx": self.s.num_ctx,
                "num_predict": self.s.num_predict, "top_p": self.s.top_p, "top_k": self.s.top_k,
                "keep_alive": self.s.keep_alive, **(info() if info else {})}

    async def _fail(self, reason: str) -> ModelUnavailable:
        self.last = reason
        if self.breaker.failure() and self.on_open is not None:
            try:
                await self.on_open(reason)
            except Exception:  # noqa: BLE001 - a notice must never break the run
                log.exception("breaker notice failed")
        return ModelUnavailable(reason)

    async def _closed(self) -> None:
        if self.on_close is not None:
            try:
                await self.on_close()
            except Exception:  # noqa: BLE001 - a notice must never break the run
                log.exception("breaker recovery notice failed")

    async def call(self, messages: list[dict[str, Any]], purpose: str, *, deadline: float | None = None,
                   tools: list[dict[str, Any]] | None = None, format: dict[str, Any] | None = None,
                   seed: int | None = None) -> Reply:
        refused = self.refusal()
        if refused:
            self.last = refused
            raise ModelUnavailable(refused)      # configuration, not the model's fault: no breaker count
        timeout = self.s.call_timeout_s
        if deadline is not None:
            timeout = min(timeout, deadline - self.clock())
            if timeout <= 1:
                raise ModelUnavailable("run_budget")   # not the model's fault: no breaker count
        if not self.breaker.allow():
            raise ModelUnavailable("circuit_open")
        token = CALL_DEADLINE.set(time.monotonic() + timeout)   # the backend's own waits must fit in this call
        try:
            reply = await asyncio.wait_for(
                self.backend.chat(messages, options=self.s.options(purpose, seed), tools=tools, format=format),
                timeout)
        except asyncio.CancelledError:
            self.breaker.release()               # cancelled: free the half-open trial slot
            raise
        except TimeoutError:
            if self.warming:
                self.breaker.release()
                raise ModelUnavailable("warming_up") from None   # queued behind the model load: not counted
            raise await self._fail("timeout") from None
        except httpx.HTTPStatusError as e:
            raise await self._fail(status_reason(e)) from None
        except ProviderLimit as e:               # the provider's limit seen before sending (Groq pacing)
            raise await self._fail(e.reason) from None
        except (httpx.HTTPError, OSError):
            raise await self._fail("unreachable") from None
        except ModelUnavailable as e:            # the backend's own guard (refusal): not counted
            self.breaker.release()
            self.last = e.reason
            raise
        except Exception as e:  # noqa: BLE001 - B2: any other transport/answer error means "model unavailable"
            log.warning("model answer unusable (%s)", type(e).__name__)
            raise await self._fail("invalid_response") from None
        finally:
            CALL_DEADLINE.reset(token)
        recovered = self.breaker.success()
        self.last = "ok"
        if recovered:
            await self._closed()
        log.info("model call %s: model=%s provider=%s tokens=%s/%s cost_usd=%s latency_ms=%s", purpose,
                 reply.model or self.s.model, reply.provider or "-", reply.tokens_in, reply.tokens_out,
                 reply.cost_usd, reply.latency_ms)
        return reply

    async def call_json(self, messages: list[dict[str, Any]], purpose: str, schema: dict[str, Any],
                        parse: Callable[[str], Any], deadline: float | None = None,
                        seed: int | None = None) -> tuple[Any, list[Call]]:
        """Structured output (JSON schema). If `parse` raises ValueError the model gets ONE retry with the error
        text; a second invalid answer counts as a failure and raises ModelUnavailable."""
        calls: list[Call] = []
        reply = await self.call(messages, purpose, deadline=deadline, format=schema, seed=seed)
        try:
            value = parse(reply.content)
            calls.append(Call(purpose, reply, False))
            return value, calls
        except ValueError as e:
            calls.append(Call(purpose, reply, False, f"invalid: {str(e)[:120]}"))
            retry = [*messages, {"role": "assistant", "content": reply.content[:2000]},
                     {"role": "user", "content": f"That answer was not valid ({str(e)[:200]}). Answer again with "
                                                 "JSON that matches the schema exactly."}]
        try:
            reply = await self.call(retry, purpose, deadline=deadline, format=schema, seed=seed)
        except ModelUnavailable as e:
            e.calls = calls  # type: ignore[attr-defined]
            raise
        try:
            value = parse(reply.content)
        except ValueError as e:
            calls.append(Call(purpose, reply, True, f"invalid: {str(e)[:120]}"))
            err = await self._fail("invalid_output")
            err.calls = calls  # type: ignore[attr-defined]
            raise err from None
        calls.append(Call(purpose, reply, True))
        return value, calls

    async def warm_up(self) -> bool:
        """One tiny call at start so the first real call does not pay the load time. A failure is logged, not
        counted by the breaker; while it runs, real calls that time out are not counted either."""
        refused = self.refusal()
        if refused:
            self.warmed = False
            log.warning("model not used (%s): the agent runs with the fixed rules only", refused)
            return False
        self.warming = True
        try:
            await asyncio.wait_for(self.backend.chat([{"role": "user", "content": "ok"}],
                                                     options=self.s.options("warm_up"), tools=None, format=None),
                                   max(self.s.call_timeout_s, 180))
        except Exception as e:  # noqa: BLE001
            log.warning("model warm-up failed (%s); the agent continues with the fixed rules until it answers",
                        type(e).__name__)
            if isinstance(e, httpx.HTTPStatusError) and status_reason(e) != "http_error":
                self.last = status_reason(e)    # a provider limit: shown in /healthz, the eval runner stops on it
            elif isinstance(e, ProviderLimit):
                self.last = e.reason
            self.warmed = False
            return False
        finally:
            self.warming = False
        self.warmed = True
        log.info("model %s warmed up", self.s.model)
        await self._closed()      # a notice left from before a restart is stale now
        return True


def model_from_env() -> Model:
    s = ModelSettings.from_env()
    return Model(backend_for(s), s, enabled=os.environ.get("MODEL_ENABLED", "1") != "0")
