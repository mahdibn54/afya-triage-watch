"""E6-4: startup sweep."""
from __future__ import annotations

from support import new_proposal

from afya_api.executor import sweep_on_startup


def test_failed_execution_keeps_the_approval_and_the_sweep_finishes_it(client, as_user, visit, fhir, conn, gateway):
    pid, _ = new_proposal(conn, fhir, visit)
    fhir.down = True
    r = client.post(f"/proposals/{pid}/approve", json={"colour": "ORANGE"})
    assert r.status_code == 200      # the decision is committed even if FHIR is down
    cid = r.json()["command_id"]
    assert conn.execute("SELECT done_at FROM commands WHERE id=%s", (cid,)).fetchone()["done_at"] is None
    fhir.down = False
    import asyncio
    results = asyncio.run(sweep_on_startup(gateway))
    assert any(x.get("command_id") == cid and x["status"] == "done" for x in results)
    assert len(fhir.data["Flag"]) == 1
    again = asyncio.run(sweep_on_startup(gateway))
    assert not any(x.get("command_id") == cid for x in again)      # nothing open any more
    assert len(fhir.data["Flag"]) == 1
