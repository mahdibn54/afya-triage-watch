"""Client for afya-mcp. The api never touches FHIR itself: every FHIR read or write goes through these tools.

/act/mcp: executor tools (record_vitals, raise_recheck_flag, notify_staff, seed_demo_visit), called with an actor.
/ui/mcp: read-only data for the screens (visit_timeline, demo_visit).
"""
from __future__ import annotations

import json
import os
from typing import Any, Protocol

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class ToolRefused(Exception):
    """The tool ran and refused (actor not allowed, unknown actor)."""


class ToolFailed(Exception):
    """The tool raised; `text` is the short error text (class name first, e.g. 'FhirNotFound: ...')."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


class McpUnavailable(Exception):
    """afya-mcp cannot be reached."""


class Gateway(Protocol):
    async def act(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...
    async def ui(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...


class McpGateway:
    def __init__(self) -> None:
        act = os.environ.get("AFYA_MCP_ACT_URL", "http://afya-mcp:9000/act/mcp")
        self.urls = {"act": act, "ui": os.environ.get("AFYA_MCP_UI_URL", act.replace("/act/mcp", "/ui/mcp"))}

    async def _call(self, mount: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        url = self.urls[mount].rstrip("/")   # no trailing slash: "/act/mcp/" would be a 307 redirect
        try:
            with anyio.fail_after(30):
                async with streamablehttp_client(url) as (r, w, _), ClientSession(r, w) as session:
                    await session.initialize()
                    res = await session.call_tool(tool, args)
        except (OSError, TimeoutError, ExceptionGroup) as e:
            raise McpUnavailable(f"afya-mcp: {type(e).__name__}") from e
        text = res.content[0].text if res.content else ""
        if res.isError:
            if "may not run" in text:
                raise ToolRefused(text)
            raise ToolFailed(text)
        return json.loads(text)

    async def act(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self._call("act", tool, args)

    async def ui(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self._call("ui", tool, args)
