"""Client for afya-mcp. The api never touches FHIR itself: every FHIR read or write goes through these tools.

/act/mcp: executor tools (record_vitals, raise_recheck_flag, notify_staff, seed_demo_visit), called with an actor.
/ui/mcp: read-only data for the screens (visit_timeline, demo_visit).
/read/mcp: the model-facing read-only tools (compute_tews, check_deterioration, get_queue_state), called by the agent
with the run_id so afya-mcp's audit row lands in the run's trace.
wso2: the borrowed WSO2 FHIR MCP server (read-only behind the GET-only gateway); the agent only ever calls `search`
and `read` on it (investigate.py wraps them).
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
    async def read(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...
    async def wso2(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...


class McpGateway:
    def __init__(self) -> None:
        act = os.environ.get("AFYA_MCP_ACT_URL", "http://afya-mcp:9000/act/mcp")
        self.urls = {"act": act, "ui": os.environ.get("AFYA_MCP_UI_URL", act.replace("/act/mcp", "/ui/mcp")),
                     "read": os.environ.get("AFYA_MCP_READ_URL", act.replace("/act/mcp", "/read/mcp")),
                     "wso2": os.environ.get("WSO2_MCP_URL", "http://wso2-fhir-mcp:8000/mcp")}

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

    async def read(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self._call("read", tool, args)

    async def wso2(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool not in ("search", "read"):   # the borrowed server also has create/update/delete: never called
            raise ToolRefused(f"{tool} is not a read-only tool")
        return await self._call("wso2", tool, args)
