"""Host-side gateway: the api's McpGateway, reaching the compose containers from the host.

The containers are not published on host ports and the host cannot resolve their service names. E13-3: the URLs stay
the service names the containers use (http://afya-mcp:9000/<mount>/mcp, https://auth.afya.internal:9091), because
OAuth needs them exactly: afya-mcp's protected-resource metadata names its resource with that URL, the authorization
server's issuer and TLS certificate use its name, and afya-mcp's Host check expects it. Only the TCP connection is
redirected: EVAL_RESOLVE maps each name to its container address (`evals/stack_env.sh` prints it); the Host header,
TLS SNI and certificate check keep the name. The OAuth flow (client credentials, per-mount scope) is the api's own
(McpGateway.auth); WSO2 gets no credential. Nothing here logs a header, a token or a secret."""
from __future__ import annotations

import json
import os
from typing import Any

import anyio
import httpx2
from afya_api.mcp_client import MODES, McpGateway, ToolFailed, ToolRefused, http_client
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


def resolve_map(text: str | None = None) -> dict[str, str]:
    """EVAL_RESOLVE="afya-mcp=172.20.0.5,auth.afya.internal=172.21.0.3" -> {"afya-mcp": "172.20.0.5", ...}"""
    out = {}
    for item in (os.environ.get("EVAL_RESOLVE", "") if text is None else text).split(","):
        name, _, addr = item.strip().partition("=")
        if name and addr:
            out[name.strip()] = addr.strip()
    return out


class ResolvingTransport(httpx2.AsyncBaseTransport):
    """Connects to the mapped address of a host name; the request keeps the name (Host header, TLS SNI and the
    certificate's name check), like an /etc/hosts entry for this process only."""

    def __init__(self, names: dict[str, str], inner: httpx2.AsyncBaseTransport | None = None) -> None:
        self.names = names
        self.inner = inner or httpx2.AsyncHTTPTransport(verify=_tls())

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        if host in self.names:
            # a copy: the SDK's OAuth flow re-sends the same request object after getting a token
            headers = httpx2.Headers(request.headers)
            headers.setdefault("Host", request.url.netloc.decode())
            request = httpx2.Request(request.method, request.url.copy_with(host=self.names[host]), headers=headers,
                                     stream=request.stream, extensions={**request.extensions, "sni_hostname": host})
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


def _tls():
    from afya_api.mcp_client import tls
    return tls()


class HostGateway(McpGateway):
    def __init__(self) -> None:
        super().__init__()
        self.names = resolve_map()

    def transport(self) -> httpx2.AsyncBaseTransport | None:
        return ResolvingTransport(self.names) if self.names else None

    async def _call(self, mount: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        url = self.urls[mount].rstrip("/")
        with anyio.fail_after(30):
            async with http_client(self.auth(mount), self.transport()) as http, \
                    Client(streamable_http_client(url, http_client=http), mode=MODES[mount], cache=None) as client:
                res = await client.call_tool(tool, args)
        text = res.content[0].text if res.content else ""
        if res.is_error:
            if "may not run" in text:
                raise ToolRefused(text)
            raise ToolFailed(text)
        return json.loads(text)
