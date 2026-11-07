"""Client for afya-mcp. The api never touches FHIR itself: every FHIR read or write goes through these tools.

/act/mcp: executor tools (record_vitals, raise_recheck_flag, notify_staff, seed_demo_visit), called with an actor.
/ui/mcp: read-only data for the screens (visit_timeline, demo_visit).
/read/mcp: the model-facing read-only tools (compute_tews, check_deterioration, get_queue_state), called by the agent
with the run_id so afya-mcp's audit row lands in the run's trace.
E12-3: afya-mcp needs `Authorization: Bearer $AFYA_MCP_TOKEN` on every mount; the token is never sent to WSO2 and
never logged.
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
from mcp.types import TextContent

from .fhir_projection import FHIRPATHS, restore_response


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

    def headers(self, mount: str) -> dict[str, str]:
        """Request headers for a mount: the afya-mcp bearer token, never sent to the borrowed WSO2 server."""
        token = os.environ.get("AFYA_MCP_TOKEN", "")
        return {"Authorization": f"Bearer {token}"} if mount != "wso2" and token else {}

    async def _call(self, mount: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        url = self.urls[mount].rstrip("/")   # no trailing slash: "/act/mcp/" would be a 307 redirect
        try:
            with anyio.fail_after(30):
                async with streamablehttp_client(url, headers=self.headers(mount)) as (r, w, _), \
                        ClientSession(r, w) as session:
                    await session.initialize()
                    res = await session.call_tool(tool, args)
        except (OSError, TimeoutError, ExceptionGroup) as e:
            raise McpUnavailable(f"afya-mcp: {type(e).__name__}") from e
        first = res.content[0] if res.content else None
        if first is not None and not isinstance(first, TextContent):
            # an image, audio or resource answer: never expected from afya-mcp or WSO2, and not parseable
            raise ToolFailed(f"{tool}: the tool answered with {type(first).__name__}, not text")
        text = first.text if first is not None else ""
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
        if args.get("type") != "Observation":
            raise ToolRefused("only Observation evidence is offered by the borrowed tools")
        # Enforced by code, not an optional argument the model can remove or broaden.
        out = await self._call("wso2", tool, {**args, "response_filter_fhirpaths": list(FHIRPATHS)})
        try:
            return restore_response(tool, out)
        except (ValueError, TypeError, AttributeError) as e:
            raise ToolFailed("invalid WSO2 projection") from e
