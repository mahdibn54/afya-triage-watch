"""Fail-closed application reporting and the official client driver's schema contract."""
from copy import deepcopy

import pytest

from scripts.conformance_client import exercise
from scripts.conformance_scope import assess_probes, assess_run


class Client:
    def __init__(self):
        self.calls = []
        self.schema = {"type": "object", "$defs": {"item": {"type": "string"}}, "allOf": [],
                       "additionalProperties": False}

    async def list_tools(self):
        from types import SimpleNamespace
        return SimpleNamespace(tools=[SimpleNamespace(name="json_schema_2020_12_tool", input_schema=self.schema),
                                      SimpleNamespace(name="json_schema_echo", input_schema={"type": "object"})])

    async def call_tool(self, name, args):
        self.calls.append((name, args))


def test_schema_scenario_echoes_the_received_schema_instead_of_sample_arguments():
    import anyio
    client = Client()
    anyio.run(exercise, client, "json-schema-2020-12-preservation")
    assert client.calls == [("json_schema_echo", {"schema": client.schema})]


def check(status="SUCCESS", name="real-check"):
    return {"id": name, "status": status}


PROFILE = {"catalogue": {"scope": "applicable", "reason": "real"},
           "image": {"scope": "fixture_dependent", "reason": "missing fixture"},
           "stateless": {"scope": "applicable", "reason": "real", "excluded_checks": {"fixture": "needs tool"}}}
DATA = {"catalogue": [check()], "image": [check("FAILURE")],
        "stateless": [check(), check("FAILURE", "fixture")]}


def test_fixture_failure_is_not_counted_as_an_application_pass():
    result = assess_run(DATA, PROFILE)
    assert result["counts"] == {"PASS": 2, "NOT_ASSESSED": 1}
    assert result["errors"] == []
    assert result["rows"][1]["raw"] == "FAIL"


def test_new_failure_in_partial_scenario_fails_the_gate():
    data = deepcopy(DATA)
    data["stateless"].append(check("FAILURE", "new-real-failure"))
    assert assess_run(data, PROFILE)["errors"]


def test_wire_schema_failure_cannot_hide_in_a_fixture_scenario():
    data = deepcopy(DATA)
    data["image"].append(check("FAILURE", "wire-schema-valid"))
    assert assess_run(data, PROFILE)["errors"]


@pytest.mark.parametrize("name", ["catalogue", "image", "stateless"])
def test_missing_scenarios_fail_even_when_out_of_scope(name):
    data = deepcopy(DATA)
    del data[name]
    assert assess_run(data, PROFILE)["errors"]


def test_unknown_scenario_and_missing_partial_check_fail():
    data = deepcopy(DATA)
    data["unexpected"] = [check()]
    data["stateless"] = [check()]
    assert len(assess_run(data, PROFILE)["errors"]) >= 2


def test_skipped_or_empty_applicable_checks_are_not_passes():
    data = deepcopy(DATA)
    data["catalogue"] = [check("SKIPPED")]
    assert assess_run(data, PROFILE)["errors"]
    data["catalogue"] = []
    assert assess_run(data, PROFILE)["errors"]


KNOWN = {"unknown-prompt-error": {"actual_code": -32603, "reason": "SDK baseline"}}


def probes():
    return [{"mount": mount, "name": name, "status": "FAIL" if name == "unknown-prompt-error" else "PASS",
             **({"actual_code": -32603} if name == "unknown-prompt-error" else {})}
            for mount in ("read", "act", "ui")
            for name in ("catalogue", "invalid-tool-arguments", "unknown-prompt-error", "unknown-tool-error")]


def test_known_sdk_failure_is_visible_and_not_counted_as_a_pass():
    result = assess_probes(probes(), KNOWN)
    assert result["counts"] == {"PASS": 9, "KNOWN_FAILURE": 3}
    assert result["errors"] == []


@pytest.mark.parametrize("status,code", [("PASS", -32602), ("FAIL", -32000), ("ERROR", None)])
def test_changed_sdk_baseline_requires_review(status, code):
    data = probes()
    data[2].update(status=status, actual_code=code)
    assert assess_probes(data, KNOWN)["errors"]


def test_missing_probe_and_unexpected_application_failure_fail():
    data = probes()
    data.pop()
    data[0]["status"] = "FAIL"
    assert len(assess_probes(data, KNOWN)["errors"]) >= 2


def test_duplicate_scenario_outputs_are_rejected(tmp_path):
    import json

    from scripts.conformance_report import scenarios
    for stamp in ("00", "01"):
        output = tmp_path / f"server-tools-list-2026-11-07T00-00-{stamp}Z"
        output.mkdir()
        (output / "checks.json").write_text(json.dumps([check()]))
    with pytest.raises(ValueError, match="Duplicate scenario output"):
        scenarios(tmp_path)


def test_generic_tool_failure_is_not_proof_of_argument_validation():
    from scripts.conformance_probe import arguments_rejected
    assert not arguments_rejected({"result": {"isError": True, "content": [{"text": "FHIR server down"}]}},
                                  ["visit_id"])
    assert arguments_rejected({"result": {"isError": True, "content": [
        {"text": "1 validation error: visit_id Field required [type=missing]"}]}}, ["visit_id"])
    assert arguments_rejected({"error": {"code": -32602}}, ["visit_id"])


def test_current_profile_does_not_waive_protocol_failures():
    from pathlib import Path

    import yaml

    profile = yaml.safe_load(Path("docs/conformance/application-profile.yaml").read_text())
    assert profile["known_probe_failures"] == {}
    data = probes()
    for probe in data:
        if probe["name"] == "unknown-prompt-error":
            probe.update(status="PASS", actual_code=-32602)
    assert assess_probes(data, profile["known_probe_failures"])["counts"] == {"PASS": 12}
    data[2].update(status="FAIL", actual_code=-32603)
    assert assess_probes(data, profile["known_probe_failures"])["errors"]


def test_report_command_writes_complete_artifacts_without_failure_baselines(tmp_path, monkeypatch):
    import json
    import sys

    import yaml

    from scripts.conformance_scope import main

    root = tmp_path / "results"
    for run in ("server-read", "server-act", "server-ui", "client"):
        output = root / run / "catalogue-2026-11-08T00-00-00Z"
        output.mkdir(parents=True)
        (output / "checks.json").write_text(json.dumps([check()]))
    data = probes()
    for probe in data:
        if probe["name"] == "unknown-prompt-error":
            probe.update(status="PASS", actual_code=-32602)
    (root / "probes.json").write_text(json.dumps(data))
    profile = tmp_path / "profile.yaml"
    rules = {"catalogue": {"scope": "applicable", "reason": "real"}}
    profile.write_text(yaml.safe_dump({"tool": "test", "protocol": "2026-07-28", "server": rules,
                                      "client": rules, "known_probe_failures": {}}))
    monkeypatch.setattr(sys, "argv", ["scope", "--root", str(root), "--profile", str(profile)])
    assert main() == 0
    assert 'No known protocol failures are accepted' in (root / "application-report.html").read_text()
    assert 'APPLICATION CHECKS PASSED' in (root / "application-report.md").read_text()
