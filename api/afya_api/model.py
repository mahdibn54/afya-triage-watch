"""E5-9: the language model client, its settings and its limits (architecture section 8).

Every call goes to Ollama's /api/chat with `think: false` set explicitly (qwen3 would otherwise think), the sampling
settings below and a seed that is logged with the call. Limits: 60 s per call, 240 s per run (the caller passes the
run's deadline), one retry on invalid JSON with the error included, and a circuit breaker that skips the model for
5 minutes after 2 failures in a row. A failure, a timeout or an open breaker raises `ModelUnavailable`; the agent then
goes on with the fixed rules only (E5-10). Nothing here decides anything clinical.

`Backend` is the transport (Ollama over HTTP, or a scripted fake in the tests); `Model` adds the limits.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

log = logging.getLogger("afya_api.model")

PURPOSES = ("map_signs", "investigate", "warm_up")


@dataclass(frozen=True)
class ModelSettings:
    base_url: str = "http://host.docker.internal:11434"
    model: str = "qwen3:8b"
    num_ctx: int = 8192
    num_predict: int = 384
    top_p: float = 0.8
    top_k: int = 20
    seed: int = 42
    keep_alive: str = "30m"
    call_timeout_s: float = 60.0
    run_timeout_s: float = 240.0
    breaker_failures: int = 2
    breaker_cooldown_s: float = 300.0
    temperatures: dict[str, float] = field(default_factory=lambda: {"map_signs": 0.0, "investigate": 0.2,
                                                                    "warm_up": 0.0})

    @classmethod
    def from_env(cls) -> ModelSettings:
        env = os.environ.get
        return cls(base_url=env("OLLAMA_BASE_URL", cls.base_url), model=env("MODEL", cls.model),
                   seed=int(env("MODEL_SEED", str(cls.seed))),
                   call_timeout_s=float(env("MODEL_CALL_TIMEOUT_SECONDS", str(cls.call_timeout_s))),
                   run_timeout_s=float(env("RUN_TIMEOUT_SECONDS", str(cls.run_timeout_s))))

    def options(self, purpose: str) -> dict[str, Any]:
        return {"num_ctx": self.num_ctx, "num_predict": 1 if purpose == "warm_up" else self.num_predict,
                "temperature": self.temperatures[purpose], "top_p": self.top_p, "top_k": self.top_k,
                "seed": self.seed}


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


class ModelUnavailable(Exception):
    """The model was not used: reason is one of circuit_open, run_budget, timeout, unreachable, http_error,
    invalid_output, disabled."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Backend(Protocol):
    async def chat(self, messages: list[dict[str, Any]], *, options: dict[str, Any],
                   tools: list[dict[str, Any]] | None, format: dict[str, Any] | None) -> Reply: ...

    async def digest(self) -> str | None: ...


class OllamaBackend:
    """Ollama /api/chat, non-streaming. `think: false` is always sent (architecture section 8)."""

    def __init__(self, settings: ModelSettings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.s, self.transport = settings, transport   # transport: tests only (httpx.MockTransport)
        self._digest: str | None = None

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
            r = await client.post("/api/chat", json=body)
        r.raise_for_status()
        d = r.json()
        msg = d.get("message") or {}
        calls = []
        for c in msg.get("tool_calls") or []:
            fn = c.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"_unparsed": True}
            calls.append({"name": str(fn.get("name", "")), "args": args if isinstance(args, dict) else {}})
        ns = 1e6
        return Reply(content=msg.get("content") or "", tool_calls=calls, tokens_in=d.get("prompt_eval_count"),
                     tokens_out=d.get("eval_count"), latency_ms=round((time.perf_counter() - start) * 1000, 1),
                     load_ms=round(d["load_duration"] / ns, 1) if d.get("load_duration") else None,
                     eval_ms=round(d["eval_duration"] / ns, 1) if d.get("eval_duration") else None,
                     model=d.get("model", self.s.model))

    async def digest(self) -> str | None:
        """The model's digest from /api/tags (logged with every call). Cached; None if Ollama is not reachable."""
        if self._digest is None:
            try:
                async with httpx.AsyncClient(base_url=self.s.base_url, timeout=5, transport=self.transport) as client:
                    tags = (await client.get("/api/tags")).json().get("models", [])
                self._digest = next((m.get("digest") for m in tags if m.get("name") == self.s.model
                                     or m.get("model") == self.s.model), None)
            except (httpx.HTTPError, OSError, ValueError):
                return None
        return self._digest


class CircuitBreaker:
    """Skip the model for `cooldown` seconds after `limit` failures in a row. One success resets the count."""

    def __init__(self, limit: int = 2, cooldown: float = 300.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.cooldown, self.clock = limit, cooldown, clock
        self.failures = 0
        self.open_until: float | None = None

    def allow(self) -> bool:
        if self.open_until is None:
            return True
        if self.clock() >= self.open_until:   # half-open: let one call try again
            self.open_until, self.failures = None, self.limit - 1
            return True
        return False

    def success(self) -> None:
        self.failures, self.open_until = 0, None

    def failure(self) -> bool:
        """Count a failure; True when this failure opens the breaker."""
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
    """The guarded model: limits, breaker, retry on invalid JSON. `on_open` runs when the breaker opens (E5-10 sends
    a model_unavailable notice from it)."""

    def __init__(self, backend: Backend, settings: ModelSettings | None = None,
                 breaker: CircuitBreaker | None = None, clock: Callable[[], float] = time.monotonic,
                 enabled: bool = True) -> None:
        self.backend, self.s, self.clock, self.enabled = backend, settings or ModelSettings(), clock, enabled
        self.breaker = breaker or CircuitBreaker(self.s.breaker_failures, self.s.breaker_cooldown_s, clock)
        self.on_open: Callable[[str], Awaitable[None]] | None = None

    def deadline(self) -> float:
        """Run budget: a run starts here and may use the model until this clock value (240 s)."""
        return self.clock() + self.s.run_timeout_s

    async def describe(self) -> dict[str, Any]:
        """Model tag, digest and settings, logged with each call (architecture section 8, 'logged per call')."""
        return {"tag": self.s.model, "digest": await self.backend.digest(), "seed": self.s.seed, "think": False,
                "num_ctx": self.s.num_ctx, "num_predict": self.s.num_predict, "top_p": self.s.top_p,
                "top_k": self.s.top_k, "keep_alive": self.s.keep_alive}

    async def _fail(self, reason: str) -> ModelUnavailable:
        if self.breaker.failure() and self.on_open is not None:
            try:
                await self.on_open(reason)
            except Exception:  # noqa: BLE001 - a notice must never break the run
                log.exception("breaker notice failed")
        return ModelUnavailable(reason)

    async def call(self, messages: list[dict[str, Any]], purpose: str, *, deadline: float | None = None,
                   tools: list[dict[str, Any]] | None = None, format: dict[str, Any] | None = None) -> Reply:
        if not self.enabled:
            raise ModelUnavailable("disabled")
        if not self.breaker.allow():
            raise ModelUnavailable("circuit_open")
        timeout = self.s.call_timeout_s
        if deadline is not None:
            timeout = min(timeout, deadline - self.clock())
            if timeout <= 1:
                raise ModelUnavailable("run_budget")   # not the model's fault: no breaker count
        try:
            reply = await asyncio.wait_for(
                self.backend.chat(messages, options=self.s.options(purpose), tools=tools, format=format), timeout)
        except TimeoutError:
            raise await self._fail("timeout") from None
        except httpx.HTTPStatusError:
            raise await self._fail("http_error") from None
        except (httpx.HTTPError, OSError):
            raise await self._fail("unreachable") from None
        self.breaker.success()
        return reply

    async def call_json(self, messages: list[dict[str, Any]], purpose: str, schema: dict[str, Any],
                        parse: Callable[[str], Any], deadline: float | None = None) -> tuple[Any, list[Call]]:
        """Structured output (Ollama `format` = JSON schema). If `parse` raises ValueError the model gets ONE retry
        with the error text; a second invalid answer counts as a failure and raises ModelUnavailable."""
        calls: list[Call] = []
        reply = await self.call(messages, purpose, deadline=deadline, format=schema)
        try:
            value = parse(reply.content)
            calls.append(Call(purpose, reply, False))
            return value, calls
        except ValueError as e:
            calls.append(Call(purpose, reply, False, f"invalid: {str(e)[:120]}"))
            retry = [*messages, {"role": "assistant", "content": reply.content[:2000]},
                     {"role": "user", "content": f"That answer was not valid ({str(e)[:200]}). Answer again with "
                                                 "JSON that matches the schema exactly."}]
        reply = await self.call(retry, purpose, deadline=deadline, format=schema)
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
        counted by the breaker."""
        if not self.enabled:
            return False
        try:
            await asyncio.wait_for(self.backend.chat([{"role": "user", "content": "ok"}],
                                                     options=self.s.options("warm_up"), tools=None, format=None),
                                   max(self.s.call_timeout_s, 180))
        except Exception as e:  # noqa: BLE001
            log.warning("model warm-up failed (%s); the agent continues with the fixed rules until it answers",
                        type(e).__name__)
            return False
        log.info("model %s warmed up", self.s.model)
        return True


def model_from_env() -> Model:
    s = ModelSettings.from_env()
    return Model(OllamaBackend(s), s, enabled=os.environ.get("MODEL_ENABLED", "1") != "0")
