"""Host-side gateway: the api's McpGateway, reaching the compose containers from the host.

The containers are not published on host ports, so the URLs are container IPs and the `Host` header carries the
service name afya-mcp / the WSO2 server expect (their DNS-rebinding check). afya-mcp also needs the bearer token
AFYA_MCP_TOKEN (E12-3; McpGateway.headers adds it, never for WSO2). `evals/stack_env.sh` prints them. Nothing
here logs a header, a URL with credentials, or a secret."""
from __future__ import annotations

import json
import os
from typing import Any

import anyio
from afya_api.mcp_client import MODES, McpGateway, ToolFailed, ToolRefused, http_client
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


class HostGateway(McpGateway):
    def __init__(self) -> None:
        super().__init__()
        mcp_host = os.environ.get("EVAL_MCP_HOST_HEADER", "afya-mcp:9000")
        wso2_host = os.environ.get("EVAL_WSO2_HOST_HEADER", "wso2-fhir-mcp:8000")
        self.hosts = {"act": mcp_host, "ui": mcp_host, "read": mcp_host, "wso2": wso2_host}

    async def _call(self, mount: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        url = self.urls[mount].rstrip("/")
        headers = {**self.headers(mount), "Host": self.hosts[mount]}
        with anyio.fail_after(30):
            async with http_client(headers) as http, \
                    Client(streamable_http_client(url, http_client=http), mode=MODES[mount], cache=None) as client:
                res = await client.call_tool(tool, args)
        text = res.content[0].text if res.content else ""
        if res.is_error:
            if "may not run" in text:
                raise ToolRefused(text)
            raise ToolFailed(text)
        return json.loads(text)
