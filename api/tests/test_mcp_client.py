"""McpGateway._call: a tool result that is not text becomes a clear ToolFailed, not an AttributeError.
E13-3: the OAuth client per mount (scope, resource, issuer) and no credential to WSO2."""
import asyncio
import base64
import contextlib
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx2
import pytest
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from mcp.types import ImageContent, TextContent

from afya_api import mcp_client
from afya_api.mcp_client import McpGateway, ToolFailed


def _gateway(monkeypatch, content, is_error=False, seen=None):
    """Fake SDK client: `seen` collects (url, auth, mode) per call."""
    class Client:
        def __init__(self, transport, mode="auto", cache=None):
            self.transport, self.mode = transport, mode

        async def __aenter__(self):
            seen is None or seen.append((*self.transport, self.mode))
            return self

        async def __aexit__(self, *_a):
            return False

        async def call_tool(self, *_a):
            return SimpleNamespace(content=content, is_error=is_error)

    @contextlib.asynccontextmanager
    async def http(auth, transport=None):
        yield auth

    monkeypatch.setattr(mcp_client, "Client", Client)
    monkeypatch.setattr(mcp_client, "http_client", http)
    monkeypatch.setattr(mcp_client, "streamable_http_client", lambda url, http_client: (url, http_client))
    return McpGateway()


def test_text_answer_is_parsed(monkeypatch):
    g = _gateway(monkeypatch, [TextContent(type="text", text='{"status": "ok"}')])
    assert asyncio.run(g.act("t", {})) == {"status": "ok"}


def test_image_answer_is_a_clear_tool_failure(monkeypatch):
    g = _gateway(monkeypatch, [ImageContent(type="image", data="AA==", mime_type="image/png")])
    with pytest.raises(ToolFailed, match="ImageContent, not text"):
        asyncio.run(g.act("t", {}))


def test_afya_mcp_calls_use_one_oauth_client_per_mount_and_wso2_calls_none(monkeypatch):
    """E13-3: each afya-mcp mount has its own client-credentials provider asking for that mount's scope only (the
    model-facing read path never holds afya:act); the borrowed WSO2 server gets no credential at all."""
    monkeypatch.setenv("AFYA_MCP_CLIENT_ID", "afya-api")
    monkeypatch.setenv("AFYA_MCP_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("AFYA_AUTH_ISSUER", "https://auth.example")
    seen: list = []
    g = _gateway(monkeypatch, [TextContent(type="text", text='{"status": "ok"}')], seen=seen)
    for call in (g.act, g.ui, g.read, g.read):
        asyncio.run(call("t", {}))
    with pytest.raises(ToolFailed):   # this fake answer is not a WSO2 Bundle; only the credentials matter here
        asyncio.run(g.wso2("search", {"type": "Observation"}))
    auths = [a for _u, a, _m in seen]
    assert all(isinstance(a, ClientCredentialsOAuthProvider) for a in auths[:4])
    assert auths[2] is auths[3]                      # reused: the token is kept until it expires
    assert len({id(a) for a in auths[:3]}) == 3      # one per mount
    scopes = [a.context.client_metadata.scope for a in auths[:3]]
    assert scopes == ["afya:act", "afya:ui", "afya:read"]
    assert [a.context.server_url for a in auths[:3]] == [g.urls["act"], g.urls["ui"], g.urls["read"]]
    assert auths[4] is None


def _flow(handler_log, *, token_status=200):
    """A mock afya-mcp /read mount and authorization server, to run the SDK's real client-credentials flow."""
    resource = "http://afya-mcp:9000/read/mcp"
    issuer = "https://auth.example"

    def handler(request: httpx2.Request) -> httpx2.Response:
        # a snapshot: the SDK adds the Authorization header to the same request object before retrying it
        handler_log.append(SimpleNamespace(url=request.url, headers=httpx2.Headers(request.headers),
                                           content=request.content))
        url = str(request.url)
        if url == resource:
            if request.headers.get("authorization") == "Bearer at-1":
                return httpx2.Response(200, json={"ok": True})
            return httpx2.Response(401, headers={"WWW-Authenticate": 'Bearer resource_metadata="http://afya-mcp:9000'
                                                 '/.well-known/oauth-protected-resource/read/mcp", scope="afya:read"'})
        if url == "http://afya-mcp:9000/.well-known/oauth-protected-resource/read/mcp":
            return httpx2.Response(200, json={"resource": resource, "authorization_servers": [issuer],
                                              "scopes_supported": ["afya:read"]})
        if url == f"{issuer}/.well-known/oauth-authorization-server":
            return httpx2.Response(200, json={"issuer": issuer, "token_endpoint": f"{issuer}/api/oidc/token",
                                              "authorization_endpoint": f"{issuer}/authorize",
                                              "grant_types_supported": ["client_credentials"],
                                              "response_types_supported": ["code"]})
        if url == f"{issuer}/api/oidc/token":
            if token_status != 200:
                return httpx2.Response(token_status, json={"error": "invalid_client"})
            return httpx2.Response(200, json={"access_token": "at-1", "token_type": "Bearer", "expires_in": 300,
                                              "scope": "afya:read"})
        return httpx2.Response(404)
    return handler


def test_client_credentials_flow_sends_resource_scope_and_basic_auth_to_the_configured_issuer(monkeypatch):
    """The SDK's real flow, offline: 401 -> RFC 9728 -> RFC 8414 -> token request (RFC 8707 resource, the mount's
    scope, client_secret_basic) -> retry with the token in the header; the second call reuses the token."""
    monkeypatch.setenv("AFYA_MCP_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("AFYA_AUTH_ISSUER", "https://auth.example")
    monkeypatch.setenv("AFYA_MCP_READ_URL", "http://afya-mcp:9000/read/mcp")
    log: list = []
    g = McpGateway()

    async def go():
        async with httpx2.AsyncClient(auth=g.auth("read"), transport=httpx2.MockTransport(_flow(log))) as c:
            assert (await c.post(g.urls["read"], json={})).status_code == 200
            assert (await c.post(g.urls["read"], json={})).status_code == 200
    asyncio.run(go())
    token_req = next(r for r in log if r.url.path == "/api/oidc/token")
    form = {k: v[0] for k, v in parse_qs(token_req.content.decode()).items()}
    assert form == {"grant_type": "client_credentials", "resource": "http://afya-mcp:9000/read/mcp",
                    "scope": "afya:read"}
    assert token_req.headers["authorization"] == "Basic " + base64.b64encode(b"afya-api:s3cret").decode()
    calls = [r for r in log if str(r.url) == g.urls["read"]]
    assert [r.headers.get("authorization") for r in calls] == [None, "Bearer at-1", "Bearer at-1"]
    for r in log:   # never a token or secret in a URL
        assert "at-1" not in str(r.url) and "s3cret" not in str(r.url)
    assert sum(r.url.path == "/api/oidc/token" for r in log) == 1


def test_a_refused_token_request_fails_closed(monkeypatch):
    monkeypatch.setenv("AFYA_MCP_CLIENT_SECRET", "wrong")
    monkeypatch.setenv("AFYA_AUTH_ISSUER", "https://auth.example")
    log: list = []
    g = McpGateway()

    async def go():
        mock = httpx2.MockTransport(_flow(log, token_status=401))
        async with httpx2.AsyncClient(auth=g.auth("read"), transport=mock) as c:
            await c.post(g.urls["read"], json={})
    with pytest.raises(Exception) as e:
        asyncio.run(go())
    assert "wrong" not in str(e.value)
    assert not any(r.headers.get("authorization", "").startswith("Bearer") for r in log)


def test_credentials_go_only_to_the_configured_issuer(monkeypatch):
    """A resource that advertises another authorization server never receives the client secret."""
    monkeypatch.setenv("AFYA_MCP_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("AFYA_AUTH_ISSUER", "https://auth.other")
    log: list = []
    g = McpGateway()

    async def go():
        async with httpx2.AsyncClient(auth=g.auth("read"), transport=httpx2.MockTransport(_flow(log))) as c:
            await c.post(g.urls["read"], json={})
    with pytest.raises(Exception):
        asyncio.run(go())
    assert not any(r.url.path == "/api/oidc/token" for r in log)
    assert not any("authorization" in r.headers and "Basic" in r.headers["authorization"] for r in log)


def test_protocol_mode_per_server(monkeypatch):
    """E13-1: afya-mcp negotiates (server/discover, 2026-07-28); the borrowed WSO2 server stays on the handshake."""
    seen: list = []
    g = _gateway(monkeypatch, [TextContent(type="text", text='{"status": "ok"}')], seen=seen)
    for call in (g.act, g.ui, g.read):
        asyncio.run(call("t", {}))
    with pytest.raises(ToolFailed):
        asyncio.run(g.wso2("search", {"type": "Observation"}))
    assert [m for _u, _h, m in seen] == ["auto", "auto", "auto", "legacy"]
