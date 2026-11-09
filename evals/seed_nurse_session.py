"""Seed the nurse-session patients for a hands-on UI check: each visit gets its confirmed colour and its FIRST reading
only. A person (or a browser driven like one) then opens each patient, records the second reading with the complaint
through the UI, and reviews what the agent proposes. Labels are NS-<case id>; synthetic data only.

    eval "$(sh evals/stack_env.sh)"
    python -m evals.seed_nurse_session [evals/cases/nurse_session]
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid

from afya_api.demo_scenario import birth_date

from .cases import load_cases
from .host_gateway import HostGateway


async def main(path: str) -> None:
    gw = HostGateway()
    for case in load_cases(path):
        label = f"NS-{case.id}"
        seeded = await gw.act("seed_demo_visit", {"label": label, "birth_date": birth_date(case.age_years),
                                                  "arrived_minutes_ago": case.arrived_minutes_ago,
                                                  "confirmed_colour": case.confirmed_colour, "actor": "system"})
        first = case.readings[0]
        saved = await gw.act("record_vitals", {"visit_id": seeded["visit_id"], "values": first["values"],
                                               "idempotency_key": f"ns-{uuid.uuid4().hex}", "actor": "nurse-a",
                                               "complaint": first.get("complaint")})
        print(json.dumps({"label": label, "visit_id": seeded["visit_id"], "first_reading": saved.get("status")}))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "evals/cases/nurse_session"))
