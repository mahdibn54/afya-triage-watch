"""HttpFhir error mapping (httpx MockTransport) and the MCP mounts over Starlette's TestClient."""
import httpx
import pytest
from starlette.testclient import TestClient

from afya_mcp.fhir import FhirNotFound, FhirRejected, FhirUnavailable, HttpFhir


def client(handler):
    f = HttpFhir("http://hapi/fhir")
    f.client = httpx.Client(base_url="http://hapi/fhir/", transport=httpx.MockTransport(handler))
    return f


@pytest.mark.parametrize("status, error", [(500, FhirUnavailable), (503, FhirUnavailable), (429, FhirUnavailable),
                                           (404, FhirNotFound), (410, FhirNotFound), (400, FhirRejected),
                                           (412, FhirRejected)])
def test_http_status_mapping(status, error):
    f = client(lambda r: httpx.Response(status, json={"resourceType": "OperationOutcome",
                                                      "issue": [{"diagnostics": "why"}]}))
    with pytest.raises(error):
        f.read("Observation", "1")


def test_timeout_is_unavailable():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)
    with pytest.raises(FhirUnavailable):
        client(boom).read("Observation", "1")


def test_requests_bypass_the_hapi_search_cache():
    # HAPI reuses an identical search for 60 s: "newest reading" must see a reading saved a moment ago.
    assert HttpFhir("http://hapi/fhir").client.headers["Cache-Control"] == "no-cache"


def test_conditional_create_header_and_bundle_parsing():
    seen = {}

    def handler(request):
        if request.method == "POST":
            seen["ine"] = request.headers["If-None-Exist"]
            return httpx.Response(201, json={"resourceType": "Observation", "id": "9"})
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={"resourceType": "Bundle", "entry": [
            {"resource": {"id": "a"}, "search": {"mode": "match"}},
            {"resource": {"id": "p"}, "search": {"mode": "include"}}]})

    f = client(handler)
    assert f.conditional_create({"resourceType": "Observation"}, "urn:afya:req|k-1")["id"] == "9"
    assert seen["ine"] == "identifier=urn:afya:req|k-1"
    assert [r["id"] for r in f.search("Observation", {"_sort": "-date"})] == ["a"]
    assert seen["query"] == {"_sort": "-date"}


def _tools(c, mount):
    r = c.post(f"/{mount}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
               headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 200, r.text
    return {t["name"]: t["inputSchema"] for line in r.text.splitlines() if line.startswith("data:")
            for t in __import__("json").loads(line[5:])["result"]["tools"]}


def test_mounts_split_read_and_act_and_check_the_host():
    # One TestClient: a session manager can only run once per process.
    from afya_mcp.server import app
    with TestClient(app, base_url="http://afya-mcp:9000") as c:
        assert c.get("/healthz").text == "ok"
        read, act, ui = _tools(c, "read"), _tools(c, "act"), _tools(c, "ui")
        assert set(read) == {"compute_tews", "check_deterioration", "get_queue_state"}
        assert set(act) == {"record_vitals", "raise_recheck_flag", "notify_staff", "seed_demo_visit"}
        assert set(ui) == {"visit_timeline", "queue_state", "demo_visit"}   # api data, no actor, not model-facing
        # E4-8: the model-facing tools have no actor field (always logged as 'agent'); act tools require one.
        for schema in read.values():
            assert "actor" not in schema["properties"] and "run_id" not in schema.get("required", [])
        for schema in act.values():
            assert "actor" in schema["required"]
        r = c.post("http://evil.example:9000/read/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream"})
        assert r.status_code == 421
