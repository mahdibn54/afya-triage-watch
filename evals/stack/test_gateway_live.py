"""Exercise real nginx and the real borrowed server, including requests that a normal client would refuse."""
import http.client
import json
import uuid

import pytest
from conftest import BASE, run


def raw(method, path, body=b"", headers=None):
    connection = http.client.HTTPConnection("gateway", 80, timeout=15)
    try:
        connection.putrequest(method, path, skip_accept_encoding=True)
        connection.putheader("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            connection.putheader(key, value)
        connection.endheaders(body)
        response = connection.getresponse()
        data = response.read()
        return response.status, data
    finally:
        connection.close()


@pytest.mark.parametrize("path", ["/fhir/Patient/..;/metadata", "/fhir/Patient/%2e%2e/metadata",
                                 "/fhir/Patient/$everything", "/fhir/Patient/%24everything"])
def test_raw_path_bypasses_are_refused_before_hapi(path):
    assert raw("GET", path)[0] == 403


def test_batch_bundle_and_method_override_cannot_write(stack):
    async def check():
        visit = await stack.visit()
        obs = (await stack.record(visit, BASE))["observation_id"]
        batch = {"resourceType": "Bundle", "type": "batch", "entry": [
            {"request": {"method": "DELETE", "url": obs}}]}
        assert raw("POST", "/fhir/", json.dumps(batch).encode(), {"Content-Type": "application/fhir+json"})[0] == 403
        for name in ("X-HTTP-Method-Override", "X-HTTP-Method", "X-Method-Override"):
            assert raw("GET", "/fhir/" + obs, headers={name: "DELETE"})[0] == 200
            assert raw("POST", "/fhir/" + obs, b"{}", {name: "GET"})[0] == 403
        assert stack.fhir.get(obs).status_code == 200
        stack.untouched(visit, "GREEN")
    run(check())


def test_actual_wso2_create_is_blocked_by_gateway(stack):
    async def check():
        marker = "group-a-" + uuid.uuid4().hex
        args = {"type": "Patient", "payload": {"resourceType": "Patient", "identifier": [
            {"system": "urn:afya:group-a", "value": marker}]}}
        # Deliberately bypass OUR client allow-list: the borrowed tool itself must fail behind nginx.
        out = await stack.gw._call("wso2", "create", args)
        assert out.get("resourceType") == "OperationOutcome", out
        assert any(i["severity"] == "error" for i in out["issue"]), out
        response = stack.fhir.get("Patient", params={"identifier": f"urn:afya:group-a|{marker}"})
        response.raise_for_status()
        assert not response.json().get("entry"), "borrowed write reached real HAPI"
    run(check())
