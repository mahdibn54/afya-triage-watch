"""E5-9 / E5-11: the language model client, its settings and its limits (architecture section 8).

Two transports (`MODEL_PROVIDER`):
- `openrouter` (default): an OPEN-WEIGHTS Qwen3 model through OpenRouter's chat completions API, with the provider
  pinned (`provider.order`, `allow_fallbacks: false`, `require_parameters: true`) and the billed `usage.cost` read
  from every answer. It is a remote service, so it is used ONLY when `DATA_CLASSIFICATION=synthetic` (the default of
  this prototype, which holds synthetic patients only). Any other value, or no `OPENROUTER_API_KEY`, refuses the call:
  the agent goes on with the fixed rules and the card says `model_unavailable`. A real deployment runs the same
  open-weights model hosted in-country (`MODEL_PROVIDER=ollama` or another local server).
- `ollama`: Ollama's /api/chat with `think: false` set explicitly (qwen3 would otherwise think).

Both get the same sampling settings and a seed that is logged with each call (the seed varies per run, derived from
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
import json
import logging
import os
import time
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

log = logging.getLogger("afya_api.model")

PURPOSES = ("map_signs", "investigate", "warm_up")
PROVIDERS = ("openrouter", "ollama")
# E5-11: chosen from https://openrouter.ai/api/v1/models (Decisions log): Qwen3-30B-A3B-Instruct-2507, Apache-2.0
# open weights, non-thinking, tools + structured outputs + seed + top_k on the pinned provider.
OPENROUTER_MODEL = "qwen/qwen3-30b-a3b-instruct-2507"
OPENROUTER_PROVIDER = "nebius/fp8"
OLLAMA_MODEL = "qwen3:8b"
SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class ModelSettings:
    provider: str = "ollama"
    base_url: str = "http://host.docker.internal:11434"
    model: str = OLLAMA_MODEL
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_provider: str = OPENROUTER_PROVIDER
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
        provider = env("MODEL_PROVIDER", "openrouter").strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(f"MODEL_PROVIDER must be one of {PROVIDERS}")
        model = env("OPENROUTER_MODEL", OPENROUTER_MODEL) if provider == "openrouter" else env("MODEL", OLLAMA_MODEL)
        keep: str | int = env("MODEL_KEEP_ALIVE", "30m")
        if isinstance(keep, str) and keep.lstrip("-").isdigit():
            keep = int(keep)          # Ollama: a number is seconds, -1 keeps the model loaded
        return cls(provider=provider, base_url=env("OLLAMA_BASE_URL", cls.base_url), model=model,
                   openrouter_url=env("OPENROUTER_BASE_URL", cls.openrouter_url),
                   openrouter_provider=env("OPENROUTER_PROVIDER", OPENROUTER_PROVIDER),
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
    cost_usd: float | None = None      # billed cost (OpenRouter usage.cost); 0 for a local model
    provider: str | None = None        # who served it (OpenRouter's answer); None for a local model


class ModelUnavailable(Exception):
    """The model was not used: reason is one of circuit_open, run_budget, timeout, warming_up, unreachable,
    http_error, invalid_response, invalid_output, disabled, data_not_synthetic, no_api_key."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Backend(Protocol):
    async def chat(self, messages: list[dict[str, Any]], *, options: dict[str, Any],
                   tools: list[dict[str, Any]] | None, format: dict[str, Any] | None) -> Reply: ...

    async def digest(self) -> str | None: ...


async def _post_with_retry(client: httpx.AsyncClient, path: str, body: dict[str, Any], s: ModelSettings,
                           headers: dict[str, str] | None = None,
                           sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> httpx.Response:
    """POST; on 429 or 5xx wait (Retry-After if given, else exponential) and try again, at most `http_retries`
    times. The caller's asyncio timeout bounds the whole thing. The last answer is raised as HTTPStatusError."""
    for attempt in range(s.http_retries + 1):
        r = await client.post(path, json=body, headers=headers)
        if (r.status_code == 429 or r.status_code >= 500) and attempt < s.http_retries:
            try:
                wait = float(r.headers.get("retry-after", ""))
            except ValueError:
                wait = s.backoff_s * 2 ** attempt
            wait = min(max(wait, 0.0), s.backoff_cap_s)
            log.warning("model HTTP %s, retry %d in %.1fs", r.status_code, attempt + 1, wait)
            await sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise AssertionError("unreachable")


class OllamaBackend:
    """Ollama /api/chat, non-streaming. `think: false` is always sent (architecture section 8)."""

    def __init__(self, settings: ModelSettings, transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.s, self.transport, self.clock = settings, transport, clock   # transport: tests (httpx.MockTransport)
        self._digest: str | None = None
        self._digest_failed_at: float | None = None

    def refusal(self) -> str | None:
        return None   # local: no data leaves the machine

    def info(self) -> dict[str, Any]:
        return {"provider": "ollama", "keep_alive": self.s.keep_alive}

    async def chat(self, messages: list[dict[str, Any]], *, options: dict[str, Any],
                   tools: list[dict[str, Any]] | None = None, format: dict[str, Any] | None = None) -> Reply:
        body: dict[str, Any] = {"model": self.s.model, "messages": messages, "stream": False, "think": False,
                                "keep_alive": self.s.keep_alive, "options": options}
        if tools:
            body["tools"] = tools
        if format is not None:
            body["format"] = format
        start = time.perf_counter()
        async with httpx.AsyncClient(base_url=self.s.base_url, timeout=None, transport=self.transport) as client:
            r = await _post_with_retry(client, "/api/chat", body, self.s)
        d = r.json()
        msg = d.get("message") or {}
        calls = []
        for c in msg.get("tool_calls") or []:
            fn = c.get("function") or {}
            calls.append({"name": str(fn.get("name", "")), "args": _args(fn.get("arguments"))})
        ns = 1e6
        return Reply(content=msg.get("content") or "", tool_calls=calls, tokens_in=d.get("prompt_eval_count"),
                     tokens_out=d.get("eval_count"), latency_ms=round((time.perf_counter() - start) * 1000, 1),
                     load_ms=round(d["load_duration"] / ns, 1) if d.get("load_duration") else None,
                     eval_ms=round(d["eval_duration"] / ns, 1) if d.get("eval_duration") else None,
                     model=d.get("model", self.s.model), cost_usd=0.0)

    async def digest(self) -> str | None:
        """The model's digest from /api/tags (logged with every call). Cached; while Ollama is unreachable the
        failure is cached for 60 s too, so a down server does not cost a 5 s wait on every step."""
        if self._digest is None:
            if self._digest_failed_at is not None and self.clock() - self._digest_failed_at < 60:
                return None
            try:
                async with httpx.AsyncClient(base_url=self.s.base_url, timeout=5, transport=self.transport) as client:
                    tags = (await client.get("/api/tags")).json().get("models", [])
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
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "answer", "strict": True, "schema": format}}
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
        if not isinstance(d, dict) or d.get("error") or not d.get("choices"):
            code = (d.get("error") or {}).get("code") if isinstance(d, dict) else None
            raise ValueError(f"provider error {code}" if code else "no choices in the answer")
        msg = d["choices"][0].get("message") or {}
        calls = [{"name": str((c.get("function") or {}).get("name", "")),
                  "args": _args((c.get("function") or {}).get("arguments"))} for c in msg.get("tool_calls") or []]
        usage = d.get("usage") or {}
        cost = usage.get("cost")
        return Reply(content=msg.get("content") or "", tool_calls=calls, tokens_in=usage.get("prompt_tokens"),
                     tokens_out=usage.get("completion_tokens"),
                     latency_ms=round((time.perf_counter() - start) * 1000, 1), model=d.get("model", self.s.model),
                     cost_usd=float(cost) if isinstance(cost, (int, float)) else None, provider=d.get("provider"))

    async def digest(self) -> str | None:
        return None   # a hosted model has no digest; the model id and the serving provider are logged instead


def backend_for(settings: ModelSettings, transport: httpx.AsyncBaseTransport | None = None) -> Backend:
    if settings.provider == "openrouter":
        return OpenRouterBackend(settings, transport)
    return OllamaBackend(settings, transport)


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

    def success(self) -> None:
        self.failures, self.open_until, self.trial = 0, None, False

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
                "seed": self.s.seed if seed is None else seed, "think": False, "num_ctx": self.s.num_ctx,
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
        except httpx.HTTPStatusError:
            raise await self._fail("http_error") from None
        except (httpx.HTTPError, OSError):
            raise await self._fail("unreachable") from None
        except ModelUnavailable as e:            # the backend's own guard (refusal): not counted
            self.breaker.release()
            self.last = e.reason
            raise
        except Exception as e:  # noqa: BLE001 - B2: any other transport/answer error means "model unavailable"
            log.warning("model answer unusable (%s)", type(e).__name__)
            raise await self._fail("invalid_response") from None
        self.breaker.success()
        self.last = "ok"
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
            self.warmed = False
            return False
        finally:
            self.warming = False
        self.warmed = True
        log.info("model %s warmed up", self.s.model)
        return True


def model_from_env() -> Model:
    s = ModelSettings.from_env()
    return Model(backend_for(s), s, enabled=os.environ.get("MODEL_ENABLED", "1") != "0")
