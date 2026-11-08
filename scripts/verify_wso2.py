"""E2-4 real-stack check. Pipe into the named containers; see docs/wso2-filter.md.

Only invented E2-4 records are created. No model is called and no patient priority is changed by the agent.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MARKER = "E2-4-OMIT-FREE-TEXT"


def fhir_client():
    from afya_mcp.fhir import HttpFhir
    fhir = HttpFhir(os.environ["FHIR_BASE_URL"])
    for attempt in range(60):
        try:
            response = fhir.client.get("metadata")
            response.raise_for_status()
            return fhir
        except Exception:
            if attempt == 59:
                raise
            time.sleep(2)


def seed():
    from afya_mcp import db, rules, services
    fhir = fhir_client()
    registry, limits = rules.load_registry(), rules.load_plausibility()
    suffix = uuid.uuid4().hex[:12]
    own = services.seed_demo_visit(fhir, f"E2-4-{suffix}", "1990-01-01", 15, "YELLOW")
    other = services.seed_demo_visit(fhir, f"E2-4-other-{suffix}", "1990-01-01", 15, "GREEN")
    base = {"resp_rate": 22, "heart_rate": 105, "systolic_bp": 120, "temperature": 37.2, "spo2": 97,
            "mobility": "walking", "consciousness": "alert", "trauma": "no"}
    ids, expected = [], {}
    for i, (visit, values) in enumerate([(own, base), (own, {**base, "heart_rate": 114, "temperature": 38.7}),
                                        (other, base)]):
        saved = services.record_vitals(fhir, limits, registry, None, visit["visit_id"], values,
                                      f"e2-4-{suffix}-{i}", when=datetime.now(timezone.utc) + timedelta(seconds=i),
                                      store=db.PgVisitStore())
        assert saved["status"] == "saved", saved["status"]
        ref = saved["observation_id"]
        obs = fhir.read("Observation", ref.split("/")[-1])
        obs["note"] = [{"text": MARKER}]
        obs["text"] = {"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{MARKER}</div>'}
        obs["subject"]["display"] = MARKER
        for comp in obs["component"]:
            comp["code"]["text"] = MARKER
            if "valueQuantity" in comp:
                comp["valueQuantity"]["unit"] = MARKER
                comp["valueQuantity"]["extension"] = [{"url": "urn:afya:e2-4", "valueString": MARKER}]
        # An unrelated component must not shift the retained HR/temperature values.
        obs["component"].append({"code": {"coding": [{"system": "urn:afya:e2-4", "code": "unrelated"}]},
                                 "valueQuantity": {"value": 999, "unit": MARKER}})
        fhir.update(obs)
        ids.append(ref)
        expected[ref] = {"resp_rate": values["resp_rate"], "heart_rate": values["heart_rate"],
                         "systolic_bp": values["systolic_bp"], "temperature": values["temperature"],
                         "spo2": values["spo2"]}
    print(json.dumps({"visit_id": own["visit_id"], "other_visit_id": other["visit_id"],
                      "own": ids[:2], "foreign": ids[2], "expected": expected}))


async def check():
    from afya_api.fhir_projection import FHIRPATHS, LOINC_ALLOW
    from afya_api.investigate import labelled, read_only_tools, trim_observation
    from afya_api.mcp_client import McpGateway, ToolRefused
    fixture = json.loads(os.environ["WSO2_CHECK_FIXTURE"])
    gw = McpGateway()
    params = {"encounter": f"Encounter/{fixture['visit_id']}", "code": "http://loinc.org|85353-1",
              "_sort": "-date", "_count": "2"}
    raw = await gw._call("wso2", "search", {"type": "Observation", "searchParam": params,
                                           "response_filter_fhirpaths": list(FHIRPATHS)})
    assert MARKER not in json.dumps(raw), "native projection leaked free text"
    assert set(raw) <= {"type", "entry", "_not_matched"}, "unexpected Bundle metadata"
    assert len(raw["entry"]) == 2
    for entry in raw["entry"]:
        assert "resource" not in entry, "pinned server's projected search shape changed"
        assert set(entry) <= {p.removeprefix("Observation.") for p in FHIRPATHS if p.startswith("Observation.")} | {
            "_not_matched"}, "native projection returned an unrequested field"
    tools = {t.name: t for t in read_only_tools(SimpleNamespace(gateway=gw), f"e2-4-{uuid.uuid4().hex}",
                                              fixture["visit_id"], fixture["own"][-1].split("/")[-1], set())}
    search = json.loads(await tools["fhir_search"].ainvoke({"count": 2}))
    assert {r["id"] for r in search["readings"]} == set(fixture["own"])
    assert [r["id"] for r in search["readings"]] == fixture["own"], "readings must be oldest first"
    assert [r["is_current"] for r in search["readings"]] == [False, True]
    for row in search["readings"]:
        assert set(row) == {"id", "time", "values", "is_current"} and row["time"]
        assert all(set(v) == {"input", "code", "value", "unit"} and v["input"] for v in row["values"])
        actual = {LOINC_ALLOW[v["code"]]: v["value"] for v in row["values"]}
        assert actual == fixture["expected"][row["id"]], "code/value association changed"
        assert all(v["unit"] in {"/min", "mm[Hg]", "Cel", "%"} for v in row["values"])
        raw_read = await gw._call("wso2", "read", {"type": "Observation", "id": row["id"].split("/")[-1],
                                                  "response_filter_fhirpaths": list(FHIRPATHS)})
        assert MARKER not in json.dumps(raw_read)
        restored = await gw.wso2("read", {"type": "Observation", "id": row["id"].split("/")[-1]})
        reading = {k: v for k, v in row.items() if k != "is_current"}
        assert labelled(trim_observation(restored)) == reading
        read = json.loads(await tools["fhir_read"].ainvoke({"observation_id": row["id"]}))
        assert read == {"reading": reading}
    refused = json.loads(await tools["fhir_read"].ainvoke({"observation_id": fixture["foreign"]}))
    assert "error" in refused, "another visit's reading was returned"
    empty = await gw.wso2("search", {"type": "Observation", "searchParam": {
        **params, "encounter": f"Encounter/e2-4-absent-{uuid.uuid4().hex[:8]}"}})
    assert empty["entry"] == []
    try:
        await gw.wso2("create", {"type": "Observation"})
    except ToolRefused:
        pass
    else:
        raise AssertionError("write tool was offered")
    print("E2-4 OK: native search/read projection, model evidence, quantities, visit scope, "
          "empty search, write refusal")


def isolation():
    assert os.environ["FHIR_SERVER_BASE_URL"] == "http://gateway/fhir"
    assert os.environ["FHIR_SERVER_DISABLE_AUTHORIZATION"] == "True"
    try:
        socket.gethostbyname("hapi")
    except socket.gaierror:
        pass
    else:
        raise AssertionError("WSO2 can resolve HAPI directly")
    with urlopen("http://gateway/fhir/metadata", timeout=20) as response:
        assert response.status == 200
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        path = f"http://gateway/fhir/Observation/e2-4-no-record-{uuid.uuid4().hex[:8]}"
        try:
            urlopen(Request(path, data=b"{}", method=method), timeout=20)
        except HTTPError as error:
            assert error.code == 403, (method, error.code)
        else:
            raise AssertionError(f"gateway accepted {method}")
    print("E2-4 OK: gateway-only routing, private demo auth setting, all write methods refused")


def finish():
    fhir = fhir_client()
    fixture = json.loads(os.environ["WSO2_CHECK_FIXTURE"])
    for key in ("visit_id", "other_visit_id"):
        encounter = fhir.read("Encounter", fixture[key])
        fhir.update({**encounter, "status": "finished"})
    print("E2-4 verification visits finished")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "check":
        asyncio.run(check())
    else:
        {"seed": seed, "isolation": isolation, "finish": finish}[mode]()
