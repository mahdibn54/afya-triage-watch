"""E13-3: the host-side gateway keeps the service names (OAuth resource, issuer, TLS name) and only redirects the
TCP connection to the container address."""
import asyncio

import httpx2

from evals.host_gateway import HostGateway, ResolvingTransport, resolve_map


def test_resolve_map_parses_and_ignores_junk():
    assert resolve_map("afya-mcp=172.20.0.5, auth.afya.internal=172.21.0.3,,bad,=x") == {
        "afya-mcp": "172.20.0.5", "auth.afya.internal": "172.21.0.3"}
    assert resolve_map("") == {}


def test_transport_connects_to_the_address_but_keeps_the_name():
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((str(request.url), request.headers["host"], request.extensions.get("sni_hostname")))
        return httpx2.Response(200)

    t = ResolvingTransport({"afya-mcp": "10.0.0.5", "auth.afya.internal": "10.0.0.6"}, httpx2.MockTransport(handler))

    async def go():
        async with httpx2.AsyncClient(transport=t) as c:
            await c.get("https://afya-mcp:9000/read/mcp")
            await c.get("https://auth.afya.internal:9091/.well-known/oauth-authorization-server")
            await c.get("http://other:80/x")
    asyncio.run(go())
    assert seen == [("https://10.0.0.5:9000/read/mcp", "afya-mcp:9000", "afya-mcp"),
                    ("https://10.0.0.6:9091/.well-known/oauth-authorization-server", "auth.afya.internal:9091",
                     "auth.afya.internal"),
                    ("http://other/x", "other", None)]


def test_host_gateway_uses_the_oauth_client_and_no_credential_for_wso2(monkeypatch):
    monkeypatch.setenv("EVAL_RESOLVE", "afya-mcp=10.0.0.5")
    g = HostGateway()
    assert g.auth("read") is not None and g.auth("act") is not None
    assert g.auth("wso2") is None
    assert isinstance(g.transport(), ResolvingTransport)
    monkeypatch.setenv("EVAL_RESOLVE", "")
    assert HostGateway().transport() is None
