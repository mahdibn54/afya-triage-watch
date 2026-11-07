"""E13-2: `server/discover` (protocol 2026-07-28) on each mount, next to the older handshake path (2025-11-25).

Raw HTTP on purpose: the wire shape (headers, error codes, no patient data) is what the specification fixes."""
import importlib.util
import json

import pytest
from starlette.testclient import TestClient

TOKEN = "t0ken-for-tests"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
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
    # and test_http_and_server.py runs the real module's app
    import os

    from afya_mcp import server as real
    spec = importlib.util.spec_from_file_location("afya_mcp._server_discovery_copy", real.__file__)
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    os.environ["AFYA_MCP_TOKEN"] = TOKEN
    server._fhir = lambda: pytest.fail("discovery must not touch FHIR")
    server._store = lambda: pytest.fail("discovery must not touch the database")
    with TestClient(server.app, base_url="http://afya-mcp:9000") as c:
        yield c
    os.environ.pop("AFYA_MCP_TOKEN", None)


@pytest.mark.parametrize("mount", MOUNTS)
def test_discover_reports_versions_identity_and_capabilities(client, mount):
    body, headers = rpc("server/discover")
    r = client.post(f"/{mount}/mcp", json=body, headers={**headers, **AUTH})
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
    text = client.post(f"/{mount}/mcp", json=body, headers={**headers, **AUTH}).text
    for forbidden in (TOKEN, "Patient/", "Encounter/", "Observation/", "postgres", "hapi", "://"):
        assert forbidden not in text


@pytest.mark.parametrize("mount", MOUNTS)
def test_unsupported_version_lists_the_supported_ones(client, mount):
    body, headers = rpc("server/discover", version="2099-01-01")
    r = client.post(f"/{mount}/mcp", json=body, headers={**headers, **AUTH})
    assert r.status_code == 400
    error = decode(r)["error"]
    assert error["code"] == -32022 and error["data"]["supported"] == ["2026-07-28"]
    assert error["data"]["requested"] == "2099-01-01"


@pytest.mark.parametrize("mount", MOUNTS)
def test_discover_needs_the_bearer_token_host_and_origin(client, mount):
    body, headers = rpc("server/discover")
    url = f"/{mount}/mcp"
    for bad in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}):
        r = client.post(url, json=body, headers={**headers, **bad})
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert client.post(f"http://evil.example:9000{url}", json=body, headers={**headers, **AUTH}).status_code == 421
    assert client.post(url, json=body, headers={**headers, **AUTH, "Origin": "http://evil.example"}).status_code == 403
    # a loopback origin is accepted (E13-4 baseline: it used to be refused)
    ok = client.post(url, json=body, headers={**headers, **AUTH, "Origin": "http://localhost:3000"})
    assert ok.status_code == 200


@pytest.mark.parametrize("mount", MOUNTS)
def test_tools_list_is_unchanged_and_separate_from_discovery(client, mount):
    body, headers = rpc("server/discover")
    assert "tools" not in decode(client.post(f"/{mount}/mcp", json=body, headers={**headers, **AUTH}))["result"]
    body, headers = rpc("tools/list")
    modern = decode(client.post(f"/{mount}/mcp", json=body, headers={**headers, **AUTH}))["result"]["tools"]
    assert {t["name"] for t in modern} == MOUNTS[mount]
    # older handshake path (the borrowed WSO2 server only speaks this): same catalogue
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "pytest", "version": "0"}}}
    r = client.post(f"/{mount}/mcp", json=init, headers={**ACCEPT, **AUTH})
    assert r.status_code == 200 and decode(r)["result"]["protocolVersion"] == "2025-11-25"
    listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    legacy = decode(client.post(f"/{mount}/mcp", json=listing, headers={**ACCEPT, **AUTH,
                                                                        "MCP-Protocol-Version": "2025-11-25"}))
    assert {t["name"] for t in legacy["result"]["tools"]} == MOUNTS[mount]
    assert {t["name"]: t["inputSchema"] for t in legacy["result"]["tools"]} == \
        {t["name"]: t["inputSchema"] for t in modern}

