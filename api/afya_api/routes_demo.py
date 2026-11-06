"""E6-6: demo endpoints, DEMO_MODE=1 only (404 otherwise). Synthetic data defined in demo_scenario.py."""
from __future__ import annotations

from afya_mcp import workflow
from fastapi import APIRouter, Depends, HTTPException

from . import helpers
from .demo_scenario import SCENARIOS, birth_date
from .deps import User, current_user, demo_mode, get_gateway
from .errors import ERROR_RESPONSES, ApiError
from .mcp_client import Gateway
from .schemas import DemoNextOut, DemoScenarioIn, DemoVisitOut


def require_demo_mode() -> None:
    if not demo_mode():
        raise HTTPException(status_code=404, detail="not found")


router = APIRouter(tags=["demo"], dependencies=[Depends(require_demo_mode)])
DEMO_ACTOR = "system"   # seeded data (record_vitals doc): the audit rows say system, not the person who clicked


async def _add_reading(gateway: Gateway, visit_id: str, n: int, reading: dict) -> str:
    try:
        out = await gateway.act("record_vitals", {
            "visit_id": visit_id, "values": reading["values"], "idempotency_key": f"demo-{visit_id}-{n}",
            "actor": DEMO_ACTOR, "complaint": reading["complaint"]})
    except Exception as e:
        raise helpers.tool_error(e) from e
    if out["status"] != "saved":
        raise ApiError(409, f"the demo reading was not saved ({out['status']})")
    return workflow.obs_ref(out["observation_id"])


@router.post("/demo/scenario", response_model=DemoVisitOut, responses=ERROR_RESPONSES)
async def load_scenario(body: DemoScenarioIn | None = None, _user: User = Depends(current_user),
                        gateway: Gateway = Depends(get_gateway)) -> DemoVisitOut:
    """Load the P-014 scenario: synthetic patient and a fresh visit confirmed YELLOW, plus the first reading
    (scored YELLOW). Loading again finishes the previous demo visit and starts a new one."""
    sc = SCENARIOS[(body or DemoScenarioIn()).name]
    try:
        seeded = await gateway.act("seed_demo_visit", {
            "label": sc["label"], "birth_date": birth_date(sc["age_years"]),
            "arrived_minutes_ago": sc["arrived_minutes_ago"], "confirmed_colour": sc["confirmed_colour"],
            "actor": DEMO_ACTOR})
    except Exception as e:
        raise helpers.tool_error(e) from e
    if seeded["status"] != "seeded":
        raise ApiError(409, f"the scenario could not be loaded ({seeded.get('reason', seeded['status'])})")
    await _add_reading(gateway, seeded["visit_id"], 1, sc["readings"][0])
    return DemoVisitOut(visit_id=seeded["visit_id"])


@router.post("/demo/scenario/next", response_model=DemoNextOut, responses=ERROR_RESPONSES)
async def next_reading(_user: User = Depends(current_user), gateway: Gateway = Depends(get_gateway)) -> DemoNextOut:
    """Add the next reading of the loaded scenario (for P-014 the one that raises the score to ORANGE).
    409 when no scenario is loaded or all its readings are in."""
    sc = SCENARIOS["p014"]
    try:
        visit = await gateway.ui("demo_visit", {"label": sc["label"]})
    except Exception as e:
        raise helpers.tool_error(e) from e
    if visit["status"] != "found":
        raise ApiError(409, "no demo scenario is loaded: load it first")
    n = visit["readings"]
    if n >= len(sc["readings"]):
        raise ApiError(409, "the scenario has no more readings")
    return DemoNextOut(obs_id=await _add_reading(gateway, visit["visit_id"], n + 1, sc["readings"][n]))
