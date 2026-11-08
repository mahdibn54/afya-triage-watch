"""Selection of the eval visits to finish: only waiting Encounters of EV- synthetic eval patients."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

from evals import eval_visits as ev


def patient(pid: str, label: str) -> dict:
    return {"resourceType": "Patient", "id": pid, "identifier": [{"system": ev.LABEL_SYSTEM, "value": label}]}


def encounter(eid: str, pid: str, status: str = "in-progress") -> dict:
    return {"resourceType": "Encounter", "id": eid, "status": status, "subject": {"reference": f"Patient/{pid}"}}


def test_only_waiting_encounters_of_ev_patients_are_selected():
    res = [patient("1", "EV-sats-adult-01-a1b2c3"), patient("2", "P-014"), patient("3", "DEMO-1"),
           patient("4", "EV-x-zzzzzz"), patient("5", "XEV-case-a1b2c3"),
           encounter("e1", "1"), encounter("e2", "2"), encounter("e3", "3"), encounter("e4", "4"),
           encounter("e5", "5"), encounter("e6", "1", "finished"), encounter("e7", "9"), encounter("e8", "1", "triaged")]
    assert [e["id"] for e in ev.select_eval_encounters(res)] == ["e1", "e8"]


def test_labels_the_runner_makes_match_and_others_do_not():
    assert ev.is_eval_label("EV-hr-red-0-1a2b3c") and not ev.is_eval_label("EV-")
    assert not ev.is_eval_label("P-014") and not ev.is_eval_label(None) and not ev.is_eval_label("EV-a-b2c3d4 ")


def test_search_pages_and_finish_only_changes_the_status():
    puts: list[httpx.Request] = []
    pages = {
        "/fhir/Encounter": {"entry": [{"resource": patient("1", "EV-a-a1b2c3")}, {"resource": encounter("e1", "1")},
                                      {"resource": patient("2", "P-014")}, {"resource": encounter("e2", "2")}],
                            "link": [{"relation": "next", "url": "http://hapi/fhir?page=2"}]},
        "/fhir": {"entry": [{"resource": patient("3", "EV-b-d4e5f6")}, {"resource": encounter("e3", "3")}]},
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "PUT":
            puts.append(req)
            return httpx.Response(200, json={})
        return httpx.Response(200, json=pages[req.url.path])

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        found = ev.find_waiting_eval_encounters(c, "http://hapi/fhir")
        assert [e["id"] for e in found] == ["e1", "e3"]
        assert puts == []                                   # finding changes nothing
        ev.finish_encounter(c, "http://hapi/fhir", found[0])
    assert len(puts) == 1 and puts[0].url.path == "/fhir/Encounter/e1"
    assert b'"finished"' in puts[0].content


def test_finish_visit_skips_a_visit_that_is_not_waiting():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.method)
        return httpx.Response(200, json=encounter("e1", "1", "finished"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert ev.finish_visit(c, "http://hapi/fhir", "Encounter/e1") is False
    assert seen == ["GET"]


def test_the_script_is_a_dry_run_unless_apply_is_given(monkeypatch, capsys):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    sys.modules.pop("finish_eval_visits", None)
    import finish_eval_visits as script
    puts = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "PUT":
            puts.append(req)
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"entry": [{"resource": patient("1", "EV-a-a1b2c3")},
                                                   {"resource": encounter("e1", "1")}]})

    real = httpx.Client
    monkeypatch.setattr(script.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("EVAL_HAPI_URL", "http://hapi/fhir")
    assert script.main([]) == 0 and puts == []
    assert "encounters (EV- patients): 1" in capsys.readouterr().out
    assert script.main(["--apply"]) == 0 and len(puts) == 1
