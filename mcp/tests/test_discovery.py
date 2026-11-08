"""E13-2: `server/discover` (protocol 2026-07-28) on each mount, next to the older handshake path (2025-11-25).

Raw HTTP on purpose: the wire shape (headers, error codes, no patient data) is what the specification fixes."""
import importlib.util
import json

import pytest
from starlette.testclient import TestClient

from oauth_fixture import bearer, mint

ACCEPT = {"Accept": "application/json, text/event-stream"}
META = "io.modelcontextprotocol/"
MOUNTS = {"read": {"compute_tews", "check_deterioration", "get_queue_state"},
          "act": {"record_vitals", "raise_recheck_flag", "notify_staff", "seed_demo_visit"},
          "ui": {"visit_timeline", "queue_state", "demo_visit"}}


def rpc(method, version="2026-07-28", params=None):
    meta = {f"{META}protocolVersion": version, f"{META}clientInfo": {"name": "pytest", "version": "0"},
            f"{META}clientCapabilities": {}}
    body = {"jsonrpc": "2.0", "id": "1", "method": method, "params": {**(params or {}), "_meta": meta}}
    return body, {**ACCEPT, "MCP-Protocol-Version": version, "Mcp-Method": method}


def decode(r):
    if r.headers["content-type"].startswith("text/event-stream"):
        return next(json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:"))
    return r.json()


@pytest.fixture(scope="module")
def client():
    # a private copy of the server module (own session managers): a session manager can only run once per process,
    # and test_http_and_server.py runs the real module's app. E13-3: tokens are signed with the local test key.
    from afya_mcp import server as real
    spec = importlib.util.spec_from_file_location("afya_mcp._server_discovery_copy", real.__file__)
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    server._fhir = lambda: pytest.fail("discovery must not touch FHIR")
    server._store = lambda: pytest.fail("discovery must not touch the database")
    with TestClient(server.app, base_url="http://afya-mcp:9000") as c:
        yield c


@pytest.mark.parametrize("mount", MOUNTS)
def test_discover_reports_versions_identity_and_capabilities(client, mount):
    body, headers = rpc("server/discover")
    r = client.post(f"/{mount}/mcp", json=body, headers={**headers, **bearer(mint(mount))})
    assert r.status_code == 200, r.text
    result = decode(r)["result"]
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == ["2026-07-28"]
    info = result["_meta"][f"{META}serverInfo"]
    assert info["name"] == f"afya-{mount}" and info["version"] and info["title"] and info["description"]
    caps = result["capabilities"]
    assert caps["tools"] == {"listChanged": False}          # a static catalogue
    assert caps["resources"].get("subscribe") is False       # no subscriptions offered
    assert not {"logging", "completions", "tasks", "extensions", "experimental"} & set(caps)
    assert result["instructions"]


@pytest.mark.parametrize("mount", MOUNTS)
def test_discover_exposes_no_patient_data_or_secret(client, mount):
    body, headers = rpc("server/discover")
    token = mint(mount)
    text = client.post(f"/{mount}/mcp", json=body, headers={**headers, **bearer(token)}).text
    for forbidden in (token, "Patient/", "Encounter/", "Observation/", "postgres", "hapi", "://"):
        assert forbidden not in text


@pytest.mark.parametrize("mount", MOUNTS)
def test_unsupported_version_lists_the_supported_ones(client, mount):
    body, headers = rpc("server/discover", version="2099-01-01")
    r = client.post(f"/{mount}/mcp", json=body, headers={**headers, **bearer(mint(mount))})
    assert r.status_code == 400
    error = decode(r)["error"]
    assert error["code"] == -32022 and error["data"]["supported"] == ["2026-07-28"]
    assert error["data"]["requested"] == "2099-01-01"


@pytest.mark.parametrize("mount", MOUNTS)
def test_discover_needs_an_access_token_host_and_origin(client, mount):
    """E13-3: the authorization spec puts a token on every HTTP request, so server/discover needs one too (the public
    discovery surface is the RFC 9728 metadata, see test_auth.py); a token without the mount's scope gets 403."""
    body, headers = rpc("server/discover")
    url = f"/{mount}/mcp"
    for bad in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": mint(mount)},
                bearer(mint(mount, expires_in=-120)), bearer(mint("read" if mount != "read" else "act"))):
        r = client.post(url, json=body, headers={**headers, **bad})
        assert r.status_code == 401 and "resource_metadata=" in r.headers["www-authenticate"]
    r = client.post(url, json=body, headers={**headers, **bearer(mint(mount, scope=""))})
    assert r.status_code == 403 and 'error="insufficient_scope"' in r.headers["www-authenticate"]
    auth = {**headers, **bearer(mint(mount))}
    assert client.post(f"http://evil.example:9000{url}", json=body, headers=auth).status_code == 421
    assert client.post(url, json=body, headers={**auth, "Origin": "http://evil.example"}).status_code == 403
    # a loopback origin is accepted (E13-4 baseline: it used to be refused)
    ok = client.post(url, json=body, headers={**auth, "Origin": "http://localhost:3000"})
    assert ok.status_code == 200


@pytest.mark.parametrize("mount", MOUNTS)
def test_tools_list_is_unchanged_and_separate_from_discovery(client, mount):
    token = bearer(mint(mount))
    body, headers = rpc("server/discover")
    assert "tools" not in decode(client.post(f"/{mount}/mcp", json=body, headers={**headers, **token}))["result"]
    body, headers = rpc("tools/list")
    modern = decode(client.post(f"/{mount}/mcp", json=body, headers={**headers, **token}))["result"]["tools"]
    assert {t["name"] for t in modern} == MOUNTS[mount]
    # older handshake path (the borrowed WSO2 server only speaks this): same catalogue
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "pytest", "version": "0"}}}
    r = client.post(f"/{mount}/mcp", json=init, headers={**ACCEPT, **bearer(mint(mount))})
    assert r.status_code == 200 and decode(r)["result"]["protocolVersion"] == "2025-11-25"
    listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    legacy = decode(client.post(f"/{mount}/mcp", json=listing, headers={**ACCEPT, **bearer(mint(mount)),
                                                                        "MCP-Protocol-Version": "2025-11-25"}))
    assert {t["name"] for t in legacy["result"]["tools"]} == MOUNTS[mount]
    assert {t["name"]: t["inputSchema"] for t in legacy["result"]["tools"]} == \
        {t["name"]: t["inputSchema"] for t in modern}



def test_whitespace_around_mcp_header_values_is_accepted(client):
    """E13-4: RFC 9110 optional whitespace around `Mcp-Method` / `Mcp-Name` values must not change the outcome."""
    body, headers = rpc("tools/call", params={"name": "no_such_tool", "arguments": {}})
    auth_h = bearer(mint("read"))
    padded = {**headers, "Mcp-Method": "  tools/call  ", "Mcp-Name": "\tno_such_tool  ", **auth_h}
    r = client.post("/read/mcp", json=body, headers=padded)
    assert r.status_code == 400, r.text
    assert decode(r)["error"]["code"] == -32602  # reached the tool layer, not a header refusal
    wrong = {**headers, "Mcp-Name": "  another_tool  ", **auth_h}
    r = client.post("/read/mcp", json=body, headers=wrong)
    assert r.status_code == 400 and decode(r)["error"]["code"] == -32020


@pytest.mark.parametrize("mount", MOUNTS)
def test_unknown_prompt_is_invalid_params_not_internal_error(client, mount):
    body, headers = rpc("prompts/get", params={"name": "not_an_afya_prompt"})
    response = client.post(f"/{mount}/mcp", json=body,
                           headers={**headers, "Mcp-Name": "not_an_afya_prompt", **bearer(mint(mount))})
    error = decode(response)["error"]
    assert error["code"] == -32602
    assert "Internal server error" not in error["message"]


@pytest.mark.parametrize("mount", MOUNTS)
def test_legacy_unknown_prompt_uses_the_same_protocol_error(client, mount):
    token = bearer(mint(mount))
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "pytest", "version": "0"}}}
    client.post(f"/{mount}/mcp", json=init, headers={**ACCEPT, **token})
    body = {"jsonrpc": "2.0", "id": 2, "method": "prompts/get", "params": {"name": "missing"}}
    response = client.post(f"/{mount}/mcp", json=body,
                           headers={**ACCEPT, **token, "MCP-Protocol-Version": "2025-11-25"})
    assert decode(response)["error"]["code"] == -32602


def test_public_prompt_override_still_delegates_registered_prompts():
    import anyio

    from afya_mcp.server import AfyaMCPServer

    server = AfyaMCPServer("prompt-hook-test")

    @server.prompt()
    def greeting(name: str) -> str:
        return f"Hello {name}"

    async def render():
        return await server.get_prompt("greeting", {"name": "test"})

    result = anyio.run(render)
    assert result.messages[0].content.text == "Hello test"


@pytest.mark.parametrize("mount", MOUNTS)
def test_unknown_tool_is_a_protocol_error(client, mount):
    body, headers = rpc("tools/call", params={"name": "not_an_afya_tool", "arguments": {}})
    response = client.post(f"/{mount}/mcp", json=body,
                           headers={**headers, "Mcp-Name": "not_an_afya_tool", **bearer(mint(mount))})
    assert decode(response)["error"]["code"] == -32602
