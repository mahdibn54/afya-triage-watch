"""Read-only checks against the real protected MCP TLS listener. No bearer token is sent here."""
import os
import ssl
from pathlib import Path

import httpx
import pytest
from afya_api.mcp_client import McpGateway


def test_actual_mcp_listener_has_a_trusted_hostname_checked_certificate():
    gateway = McpGateway()
    assert all(gateway.urls[m].startswith("https://afya-mcp:9000/") for m in ("read", "act", "ui"))
    context = ssl.create_default_context(cafile=os.environ["AFYA_AUTH_CA_FILE"])
    with httpx.Client(verify=context, timeout=30) as client:
        assert client.get("https://afya-mcp:9000/healthz").text == "ok"
    assert not Path("/mcp-tls/server.private.pem").exists()  # runner has only the public CA


def test_actual_mcp_listener_rejects_untrusted_tls_and_plaintext():
    with httpx.Client(verify=True, timeout=30) as client:
        with pytest.raises(httpx.ConnectError, match="(?i)certificate.verify.failed"):
            client.get("https://afya-mcp:9000/healthz")
        with pytest.raises(httpx.HTTPError):
            client.get("http://afya-mcp:9000/healthz").raise_for_status()
