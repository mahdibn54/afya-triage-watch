"""A deterministic stand-in for Ollama: the tests script what the model answers, per purpose (map_signs,
investigate). Same interface as model.OllamaBackend, so the real limits, retry and breaker of model.Model apply."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from afya_api.model import Reply

Answer = Reply | BaseException | Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], Reply]


def signs_reply(verdict: str, *signs: tuple[str, str, str]) -> Reply:
    """map_signs answer: signs as (code, quote, status)."""
    return Reply(json.dumps({"verdict": verdict, "signs": [{"code": c, "quote": q, "status": s} for c, q, s in signs]}),
                 tokens_in=500, tokens_out=40, latency_ms=900.0)


def tool_call(name: str, **args: Any) -> Reply:
    return Reply("", tool_calls=[{"name": name, "args": args}], tokens_in=800, tokens_out=30, latency_ms=700.0)


def decision(action: str = "propose", rationale: str = "", cited_ids: list[str] | None = None,
             extra_triggers: list[str] | None = None, missing_input: str | None = None) -> Reply:
    args: dict[str, Any] = {"action": action, "extra_triggers": extra_triggers or [], "rationale": rationale,
                            "cited_ids": cited_ids or []}
    if missing_input is not None:
        args["missing_input"] = missing_input
    return tool_call("submit_decision", **args)


class ScriptedBackend:
    """answers[purpose] is a list consumed in order; when it runs out the model is 'down' (connection refused)."""

    def __init__(self) -> None:
        self.answers: dict[str, list[Answer]] = {"map_signs": [], "investigate": [], "warm_up": []}
        self.seen: list[dict[str, Any]] = []

    def script(self, purpose: str, *answers: Answer) -> ScriptedBackend:
        self.answers[purpose].extend(answers)
        return self

    async def chat(self, messages, *, options, tools=None, format=None) -> Reply:
        purpose = "map_signs" if format is not None else "investigate" if tools else "warm_up"
        self.seen.append({"purpose": purpose, "messages": messages, "options": options, "tools": tools,
                          "format": format})
        queue = self.answers[purpose]
        if not queue:
            raise httpx.ConnectError("scripted model: no answer left (model down)")
        a = queue.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a(messages, tools) if callable(a) else a

    async def digest(self) -> str | None:
        return "sha256:scripted"
