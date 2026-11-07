"""Client for afya-mcp. The api never touches FHIR itself: every FHIR read or write goes through these tools.

/act/mcp: executor tools (record_vitals, raise_recheck_flag, notify_staff, seed_demo_visit), called with an actor.
/ui/mcp: read-only data for the screens (visit_timeline, demo_visit).
/read/mcp: the model-facing read-only tools (compute_tews, check_deterioration, get_queue_state), called by the agent
with the run_id so afya-mcp's audit row lands in the run's trace.
E13-3: OAuth 2.1 client credentials (MCP authorization, 2026-07-28). The api is a confidential service client
(AFYA_MCP_CLIENT_ID / AFYA_MCP_CLIENT_SECRET, pre-registered at the authorization server AFYA_AUTH_ISSUER). The SDK's
ClientCredentialsOAuthProvider does the whole flow per mount: 401 -> RFC 9728 metadata -> RFC 8414 metadata of the
configured issuer only -> token request with the mount's `resource` (RFC 8707) and only that mount's scope -> retry.
So the read path's token carries afya:read for /read/mcp and nothing else; afya:act tokens exist only on the /act
path (fixed code: the executor after a nurse's approval, saving vitals, notices). Tokens live in memory, in the
Authorization header only (never in a URL), are never logged and never sent to WSO2 (no auth on that mount at all).
E13-1: protocol versions. afya-mcp is called with `mode="auto"` (mcp SDK 2.x: probe `server/discover`, use protocol
2026-07-28, fall back to the `initialize` handshake if the server is older). The borrowed WSO2 server only speaks the
older handshake protocols, so it is called with `mode="legacy"` (an explicit supported-version path, no probe).
wso2: the borrowed WSO2 FHIR MCP server (read-only behind the GET-only gateway); the agent only ever calls `search`
and `read` on it (investigate.py wraps them).
"""
from __future__ import annotations

import json
import os
import ssl
from typing import Any, Protocol

import anyio
import httpx2
from mcp import Client
from mcp.client.auth import OAuthFlowError, TokenStorage
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
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


# Per mount: how the SDK negotiates the protocol version (see the module docstring).
MODES = {"act": "auto", "ui": "auto", "read": "auto", "wso2": "legacy"}
# E13-3: the one scope each afya-mcp mount needs (least privilege). WSO2 gets no credential at all.
SCOPES = {"act": "afya:act", "ui": "afya:ui", "read": "afya:read"}


class MemoryTokens(TokenStorage):
    """Tokens of one mount, in this process's memory only (never written to disk, a log or the database)."""

    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client = client_info


def tls() -> ssl.SSLContext:
    """Trust for the authorization server's TLS certificate: the local CA (AFYA_AUTH_CA_FILE) plus the system store."""
    ctx = ssl.create_default_context()
    if os.environ.get("AFYA_AUTH_CA_FILE"):
        ctx.load_verify_locations(cafile=os.environ["AFYA_AUTH_CA_FILE"])
    return ctx


def http_client(auth: httpx2.Auth | None, transport: httpx2.AsyncBaseTransport | None = None) -> httpx2.AsyncClient:
    """The SDK 2.x transport takes its auth and timeouts from the http client (v1's defaults)."""
    return httpx2.AsyncClient(auth=auth, verify=tls(), transport=transport, timeout=httpx2.Timeout(30, read=300))


class McpGateway:
    def __init__(self) -> None:
        act = os.environ.get("AFYA_MCP_ACT_URL", "http://afya-mcp:9000/act/mcp")
        self.urls = {"act": act, "ui": os.environ.get("AFYA_MCP_UI_URL", act.replace("/act/mcp", "/ui/mcp")),
                     "read": os.environ.get("AFYA_MCP_READ_URL", act.replace("/act/mcp", "/read/mcp")),
                     "wso2": os.environ.get("WSO2_MCP_URL", "http://wso2-fhir-mcp:8000/mcp")}

        self._auth: dict[str, ClientCredentialsOAuthProvider] = {}

    def auth(self, mount: str) -> httpx2.Auth | None:
        """E13-3: the OAuth client of one afya-mcp mount (kept, so its token is reused until it expires); None for
        the borrowed WSO2 server, which never receives any afya credential. Without client credentials afya-mcp
        answers 401 and the call fails as unavailable (fail closed)."""
        if mount not in SCOPES:
            return None
        if mount not in self._auth:
            self._auth[mount] = ClientCredentialsOAuthProvider(
                server_url=self.urls[mount].rstrip("/"), storage=MemoryTokens(),
                client_id=os.environ.get("AFYA_MCP_CLIENT_ID", "afya-api"),
                client_secret=os.environ.get("AFYA_MCP_CLIENT_SECRET", ""),
                scope=SCOPES[mount], issuer=os.environ.get("AFYA_AUTH_ISSUER", "https://auth.afya.internal:9091"))
        return self._auth[mount]

    def transport(self) -> httpx2.AsyncBaseTransport | None:
        """Default transport (the host-side eval gateway maps service names to container addresses here)."""
        return None

    async def _call(self, mount: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        url = self.urls[mount].rstrip("/")   # no trailing slash: "/act/mcp/" would be a 307 redirect
        try:
            with anyio.fail_after(30):
                async with http_client(self.auth(mount), self.transport()) as http, \
                        Client(streamable_http_client(url, http_client=http), mode=MODES[mount], cache=None) as client:
                    res = await client.call_tool(tool, args)
        except (OSError, TimeoutError, ExceptionGroup, httpx2.HTTPError, OAuthFlowError) as e:
            raise McpUnavailable(f"afya-mcp: {type(e).__name__}") from e
        first = res.content[0] if res.content else None
        if first is not None and not isinstance(first, TextContent):
            # an image, audio or resource answer: never expected from afya-mcp or WSO2, and not parseable
            raise ToolFailed(f"{tool}: the tool answered with {type(first).__name__}, not text")
        text = first.text if first is not None else ""
        if res.is_error:
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
