"""E6-3: approve is one transaction, then the executor runs (resume_after_approval)."""
from __future__ import annotations

import uuid

from afya_mcp import workflow
from support import error, new_proposal

from afya_api.executor import resume_after_approval


def test_approve_runs_the_executor_and_writes_the_flag(client, as_user, visit, fhir, conn, gateway):
    pid, oid = new_proposal(conn, fhir, visit)
    r = client.post(f"/proposals/{pid}/approve", json={"colour": "ORANGE", "signs_kept": ["SOB_ACUTE"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["proposal_id"] == pid and body["status"] == "approved" and uuid.UUID(body["command_id"])
    flags = list(fhir.data["Flag"].values())
    assert len(flags) == 1 and flags[0]["identifier"][0]["value"] == body["command_id"]
    enc = fhir.data["Encounter"][visit]
    assert {"system": "urn:afya:sats-colour", "code": "ORANGE"} in enc["priority"]["coding"]
    run_id = workflow.run_id_for(visit, oid)   # S4: the run id goes with the fallback executor too
    assert ("raise_recheck_flag", {"command_id": body["command_id"], "actor": "nurse-a", "run_id": run_id}) \
        in gateway.calls
    cmd = conn.execute("SELECT done_at FROM commands WHERE id=%s", (body["command_id"],)).fetchone()
    assert cmd["done_at"] is not None
    error(client.post(f"/proposals/{pid}/approve", json={"colour": "ORANGE"}), 409, "conflict")


def test_approve_override_to_a_lower_colour_with_reason(client, as_user, visit, fhir, conn):
    pid, _ = new_proposal(conn, fhir, visit)
    e = error(client.post(f"/proposals/{pid}/approve", json={"colour": "GREEN"}), 422, "invalid")
    assert "override_reason" in e["message"]
    assert conn.execute("SELECT status FROM proposals WHERE id=%s", (pid,)).fetchone()["status"] == "pending"
    r = client.post(f"/proposals/{pid}/approve", json={"colour": "GREEN", "override_reason": "cuff error"})
    assert r.status_code == 200
    flag = next(iter(fhir.data["Flag"].values()))
    assert {"url": "urn:afya:sats-colour", "valueCode": "GREEN"} in flag["extension"]
    assert {"system": "urn:afya:sats-colour", "code": "GREEN"} in fhir.data["Encounter"][visit]["priority"]["coding"]


def test_resume_after_approval_is_idempotent_and_never_raises(gateway, visit, fhir, conn):
    import asyncio
    pid, _ = new_proposal(conn, fhir, visit)
    cid = str(workflow.approve_proposal(conn, pid, "clin-m")["command"]["id"])
    first = asyncio.run(resume_after_approval(cid, gateway=gateway))
    second = asyncio.run(resume_after_approval(cid, gateway=gateway))
    assert (first["status"], second["status"]) == ("done", "already_done")
    assert gateway.calls[0][1]["actor"] == "clin-m"      # the approving user, looked up from the proposal
    assert asyncio.run(resume_after_approval(str(uuid.uuid4()), gateway=gateway))["status"] == "not_found"


def test_a_command_whose_visit_is_gone_logs_the_cause_not_just_toolfailed(caplog):
    """E12-6 (E12-2 follow-up): the startup log names the cause (FHIR 404 after a reset) and the abandon rule."""
    import asyncio
    import logging

    from afya_api.executor import run_command
    from afya_api.mcp_client import ToolFailed

    class Gw:
        async def act(self, tool, args):
            raise ToolFailed("FhirNotFound: GET Encounter/v1: HTTP 404")

    with caplog.at_level(logging.WARNING, logger="afya_api.executor"):
        out = asyncio.run(run_command(Gw(), "c1", "nurse-a"))
    assert out["status"] == "failed"
    assert "FhirNotFound" in caplog.text and "cannot succeed" in caplog.text and "abandoned" in caplog.text
