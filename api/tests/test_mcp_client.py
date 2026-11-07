"""McpGateway._call: a tool result that is not text becomes a clear ToolFailed, not an AttributeError."""
import asyncio
import contextlib
from types import SimpleNamespace

import pytest
from mcp.types import ImageContent, TextContent

from afya_api import mcp_client
from afya_api.mcp_client import McpGateway, ToolFailed


def _gateway(monkeypatch, content, is_error=False, seen=None):
    class Session:
        def __init__(self, *_a):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def initialize(self):
            pass

        async def call_tool(self, *_a):
            return SimpleNamespace(content=content, isError=is_error)

    @contextlib.asynccontextmanager
    async def client(url, headers=None):
        if seen is not None:
            seen.append((url, headers))
        yield (None, None, None)

    monkeypatch.setattr(mcp_client, "ClientSession", Session)
    monkeypatch.setattr(mcp_client, "streamablehttp_client", client)
    return McpGateway()


def test_text_answer_is_parsed(monkeypatch):
    g = _gateway(monkeypatch, [TextContent(type="text", text='{"status": "ok"}')])
    assert asyncio.run(g.act("t", {})) == {"status": "ok"}


def test_image_answer_is_a_clear_tool_failure(monkeypatch):
    g = _gateway(monkeypatch, [ImageContent(type="image", data="AA==", mimeType="image/png")])
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
    assert [h for _u, h in seen[:3]] == [{"Authorization": "Bearer tok-123"}] * 3
    assert seen[3][1] == {}
