"""McpGateway._call: a tool result that is not text becomes a clear ToolFailed, not an AttributeError."""
import asyncio
import contextlib
from types import SimpleNamespace

import pytest
from mcp.types import ImageContent, TextContent

from afya_api import mcp_client
from afya_api.mcp_client import McpGateway, ToolFailed


def _gateway(monkeypatch, content, is_error=False, seen=None):
    """Fake SDK client: `seen` collects (url, headers, mode) per call."""
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
    async def http(headers):
        yield headers

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


def test_afya_mcp_calls_carry_the_bearer_token_and_wso2_calls_do_not(monkeypatch):
    """E12-3: afya-mcp's mounts need the token; it must never leak to the borrowed WSO2 server."""
    monkeypatch.setenv("AFYA_MCP_TOKEN", "tok-123")
    seen: list = []
    g = _gateway(monkeypatch, [TextContent(type="text", text='{"status": "ok"}')], seen=seen)
    for call in (g.act, g.ui, g.read):
        asyncio.run(call("t", {}))
    with pytest.raises(ToolFailed):   # this fake answer is not a WSO2 Bundle; only the headers matter here
        asyncio.run(g.wso2("search", {"type": "Observation"}))
    assert [h for _u, h, _m in seen[:3]] == [{"Authorization": "Bearer tok-123"}] * 3
    assert seen[3][1] == {}


def test_protocol_mode_per_server(monkeypatch):
    """E13-1: afya-mcp negotiates (server/discover, 2026-07-28); the borrowed WSO2 server stays on the handshake."""
    seen: list = []
    g = _gateway(monkeypatch, [TextContent(type="text", text='{"status": "ok"}')], seen=seen)
    for call in (g.act, g.ui, g.read):
        asyncio.run(call("t", {}))
    with pytest.raises(ToolFailed):
        asyncio.run(g.wso2("search", {"type": "Observation"}))
    assert [m for _u, _h, m in seen] == ["auto", "auto", "auto", "legacy"]
