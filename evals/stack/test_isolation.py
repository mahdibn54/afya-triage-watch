"""Run INSIDE the real WSO2 server container, not the Group A runner."""
import os
import socket
from urllib.request import urlopen

import pytest


@pytest.fixture(scope="session", autouse=True)
def provenance(record_testsuite_property):
    record_testsuite_property("code_commit", os.environ.get("GROUP_A_COMMIT", "uncommitted"))
    record_testsuite_property("execution", "inside real pinned WSO2 server container")


def test_wso2_gateway_route_and_private_demo_auth():
    assert os.environ["FHIR_SERVER_BASE_URL"] == "http://gateway/fhir"
    assert os.environ["FHIR_SERVER_DISABLE_AUTHORIZATION"] == "True"
    with urlopen("http://gateway/fhir/metadata", timeout=20) as response:
        assert response.status == 200


def test_wso2_cannot_resolve_hapi_directly():
    with pytest.raises(socket.gaierror):
        socket.gethostbyname("hapi")


def test_wso2_cannot_connect_to_hapi_by_ip_either():
    # A known-live HAPI behind the gateway makes this a network-boundary check, not a server-outage check.
    with urlopen("http://gateway/fhir/metadata", timeout=20) as response:
        assert response.status == 200
    with pytest.raises(OSError):
        connection = socket.create_connection((os.environ["GROUP_A_HAPI_IP"], 8080), timeout=2)
        connection.close()
