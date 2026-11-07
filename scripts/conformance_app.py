"""Local ASGI wrapper for running the official MCP conformance tool against afya-mcp (E13-4).

The conformance CLI cannot send an Authorization header, and afya-mcp (rightly) requires one on every mount. This
wrapper imports the real server app and adds the bearer token (read from AFYA_MCP_TOKEN in the environment of the
process, never printed or stored) to each incoming request. Auth itself is covered by the mcp unit tests, not by the
conformance run. Run: AFYA_MCP_TOKEN=<throwaway> uvicorn conformance_app:app --app-dir scripts --port 9100
"""
from __future__ import annotations

import os
from typing import Any

from afya_mcp.server import app as _app


async def app(scope: dict, receive: Any, send: Any) -> None:
    if scope["type"] in ("http", "lifespan"):
        if scope["type"] == "http":
            token = os.environ["AFYA_MCP_TOKEN"].encode()
            scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k != b"authorization"]
                     + [(b"authorization", b"Bearer " + token)]}
        await _app(scope, receive, send)
