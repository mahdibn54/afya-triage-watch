"""E4-8: the audit wrapper (actor check, timing, trimming, failure handling) with an in-memory auditor."""
import json
import logging

import pytest

from afya_mcp import audit
from afya_mcp.fhir import FhirRejected, FhirUnavailable

USERS = {"nurse-a": "nurse", "clin-m": "clinician", "mgr-k": "manager", "agent": "agent", "system": "system"}


class FakeAuditor:
    def __init__(self, fail: bool = False) -> None:
        self.rows: list[dict] = []
        self.fail = fail

    def role(self, user_id):
        return USERS.get(user_id)

    def write(self, kind, actor, auth, visit_id, run_id, payload):
        if self.fail:
            raise ConnectionError("database down")
        json.dumps(payload)   # must be JSON-serialisable as stored
        self.rows.append(dict(kind=kind, actor=actor, auth=auth, visit_id=visit_id, run_id=run_id, payload=payload))


def test_read_call_is_logged_as_agent_with_latency_inputs_and_output():
    a = FakeAuditor()
    out = audit.call(a, "check_deterioration", audit.READ, {"visit_id": "Encounter/v014"},
                     lambda: {"status": "checked", "visit_id": "v014"}, run_id="run-1")
    assert out["status"] == "checked"
    [row] = a.rows
    assert (row["kind"], row["actor"], row["auth"], row["visit_id"], row["run_id"]) == \
        ("check_deterioration", "agent", "service", "v014", "run-1")
    p = row["payload"]
    assert p["mount"] == "read" and p["inputs"] == {"visit_id": "Encounter/v014"}
    assert p["output"]["status"] == "checked" and p["error"] is None and p["latency_ms"] >= 0


def test_act_call_records_the_human_actor():
    a = FakeAuditor()
    audit.call(a, "record_vitals", audit.ACT, {"visit_id": "v1", "values": {"heart_rate": 80}},
               lambda: {"status": "saved"}, actor="nurse-a")
    assert (a.rows[0]["actor"], a.rows[0]["auth"], a.rows[0]["visit_id"]) == ("nurse-a", "demo_switcher", "v1")


@pytest.mark.parametrize("actor", ["mgr-k", "nobody", "", None])
def test_act_call_refuses_manager_and_unknown_actor_before_running(actor):
    a = FakeAuditor()
    ran = []
    with pytest.raises(audit.ActorRefused):
        audit.call(a, "raise_recheck_flag", audit.ACT, {"command_id": "c1"}, lambda: ran.append(1), actor=actor)
    assert ran == []
    [row] = a.rows
    assert row["kind"] == "raise_recheck_flag_refused"
    assert row["actor"] == ("mgr-k" if actor == "mgr-k" else "system")   # unknown ids cannot be the FK actor


def test_errors_are_audited_then_reraised():
    a = FakeAuditor()

    def boom():
        raise FhirUnavailable("GET Encounter/v1: HTTP 503")
    with pytest.raises(FhirUnavailable):
        audit.call(a, "check_deterioration", audit.READ, {"visit_id": "v1"}, boom)
    assert a.rows[0]["payload"]["error"] == "FhirUnavailable: GET Encounter/v1: HTTP 503"
    assert a.rows[0]["payload"]["output"] is None


def test_fhir_diagnostics_never_reach_the_audit_log():
    e = FhirRejected("POST Observation: HTTP 422: Patient Jane Doe says she feels faint")
    assert audit.error_text(e) == "FhirRejected: POST Observation: HTTP 422"


def test_act_tool_fails_when_the_audit_insert_fails():
    a = FakeAuditor(fail=True)
    with pytest.raises(audit.AuditFailed):
        audit.call(a, "notify_staff", audit.ACT, {"kind": "vitals_due"}, lambda: {"status": "sent"}, actor="system")


def test_act_tool_does_not_run_without_an_audit_log():
    ran = []
    with pytest.raises(audit.AuditFailed):
        audit.call(None, "record_vitals", audit.ACT, {}, lambda: ran.append(1), actor="nurse-a")
    assert ran == []


def test_read_tool_still_answers_when_the_audit_insert_fails_but_logs_it(caplog):
    a = FakeAuditor(fail=True)
    with caplog.at_level(logging.ERROR, logger="afya_mcp.audit"):
        assert audit.call(a, "compute_tews", audit.READ, {}, lambda: {"status": "scored"}) == {"status": "scored"}
    assert "not written" in caplog.text


def test_payloads_are_trimmed():
    a = FakeAuditor()
    big = {"patients": [{"visit_id": f"v{i}", "note": "x" * 500} for i in range(200)]}
    audit.call(a, "get_queue_state", audit.READ, {"s": "y" * 1000}, lambda: big)
    p = a.rows[0]["payload"]
    assert len(json.dumps(p)) <= audit.MAX_BYTES
    assert len(p["inputs"]["s"]) == audit.MAX_STR


def test_trim_caps_strings_lists_and_depth():
    t = audit.trim({"a": "z" * 300, "l": list(range(100)), "d": {"1": {"2": {"3": {"4": {"5": {"6": 1}}}}}}})
    assert len(t["a"]) == audit.MAX_STR
    assert len(t["l"]) == audit.MAX_ITEMS + 1 and t["l"][-1] == "... 75 more"
    assert "..." in json.dumps(t["d"])


# ---------- E12-2: intent row for tools whose effect commits before the audit row ----------

class FailsAfter(FakeAuditor):
    """Writes the first `ok` rows, then fails."""
    def __init__(self, ok: int) -> None:
        super().__init__()
        self.ok = ok

    def write(self, *a):
        if len(self.rows) >= self.ok:
            raise ConnectionError("database down")
        super().write(*a)


def test_intent_row_comes_first_and_the_final_row_follows():
    a = FakeAuditor()
    audit.call(a, "record_vitals", audit.ACT, {"visit_id": "v1"}, lambda: {"status": "saved"}, actor="nurse-a",
               intent=True)
    assert [r["kind"] for r in a.rows] == ["record_vitals_started", "record_vitals"]
    assert a.rows[0]["visit_id"] == "v1" and "output" not in a.rows[0]["payload"]


def test_without_an_intent_row_the_effect_does_not_happen():
    ran = []
    with pytest.raises(audit.AuditFailed):
        audit.call(FakeAuditor(fail=True), "record_vitals", audit.ACT, {"visit_id": "v1"}, lambda: ran.append(1),
                   actor="nurse-a", intent=True)
    assert ran == []


def test_when_only_the_final_row_fails_the_result_stands_and_the_intent_row_is_the_record(caplog):
    a = FailsAfter(1)
    with caplog.at_level(logging.ERROR, logger="afya_mcp.audit"):
        out = audit.call(a, "record_vitals", audit.ACT, {"visit_id": "v1"}, lambda: {"status": "saved"},
                         actor="nurse-a", intent=True)
    assert out == {"status": "saved"} and [r["kind"] for r in a.rows] == ["record_vitals_started"]
    assert "record_vitals_started row is the record" in caplog.text
