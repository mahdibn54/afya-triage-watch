"""McpGateway._call: a tool result that is not text becomes a clear ToolFailed, not an AttributeError."""
import asyncio
import contextlib
from types import SimpleNamespace

import pytest
from mcp.types import ImageContent, TextContent

from afya_api import mcp_client
from afya_api.mcp_client import McpGateway, ToolFailed


def _gateway(monkeypatch, content, is_error=False):
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
    async def client(_url):
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
