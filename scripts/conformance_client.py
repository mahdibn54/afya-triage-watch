"""Client under test for the official MCP conformance tool (E13-4): the api's own client stack, nothing else.

Run by `conformance client --command "<python> scripts/conformance_client.py"`: the tool starts a mock server (and, for
the authorization scenarios, a mock authorization server), appends its URL and sets MCP_CONFORMANCE_SCENARIO and, where a
scenario needs it, MCP_CONFORMANCE_CONTEXT. This uses what afya_api.mcp_client uses for afya-mcp: the SDK `Client` in
`mode="auto"` over `streamable_http_client`, with `ClientCredentialsOAuthProvider` + `MemoryTokens` when the scenario
hands out client credentials. The api implements no other OAuth flow (no authorization code, no PKCE, no dynamic or
CIMD registration: its callers are services), so scenarios that need those are not applicable and are recorded as
expected failures in docs/conformance/expected-failures.yaml, never as passes.
Run: PYTHONPATH=api python scripts/conformance_client.py <server-url>
"""
from __future__ import annotations

import json
import os
import sys

import anyio
from afya_api.mcp_client import SCOPES, MemoryTokens, http_client
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from mcp.client.streamable_http import streamable_http_client

from mcp import Client


def sample(schema: dict, text: str = "x") -> dict:
    """Minimal arguments that satisfy a tool's input schema (the mock tools are simple): required properties only."""
    out = {}
    for name, prop in (schema.get("properties") or {}).items():
        if name not in (schema.get("required") or []):
            continue
        out[name] = {"number": 1, "integer": 1, "boolean": True, "array": [], "object": {}}.get(prop.get("type"), text)
    return out


async def main(url: str) -> None:
    ctx = json.loads(os.environ.get("MCP_CONFORMANCE_CONTEXT") or "{}")
    auth = None
    if ctx.get("client_id") and ctx.get("client_secret"):
        auth = ClientCredentialsOAuthProvider(server_url=url, storage=MemoryTokens(), client_id=ctx["client_id"],
                                              client_secret=ctx["client_secret"], scope=ctx.get("scope"))
    async with http_client(auth) as http, Client(streamable_http_client(url, http_client=http), mode="auto",
                                                 cache=None) as client:
        for tool in (await client.list_tools()).tools:
            # twice: plain strings, then values that need Base64 in an Mcp-Param header (non-ASCII, padding, newline)
            for text in ("x", " h\u00e9llo\nw "):
                await client.call_tool(tool.name, sample(tool.input_schema, text))


if __name__ == "__main__":
    _ = SCOPES  # the api's scope table is part of the client module under test
    anyio.run(main, sys.argv[1])
