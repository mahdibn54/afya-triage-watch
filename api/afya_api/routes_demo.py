"""E6-6: demo endpoints, DEMO_MODE=1 only (404 otherwise). Synthetic data defined in demo_scenario.py.

E12-3: only a nurse or clinician may load the scenario or add its readings (403 for a manager, who reads only), and
each click writes one `demo_scenario` audit row with the signed-in user as actor. The readings themselves stay
seeded data (actor `system`), as before."""
from __future__ import annotations

from typing import Any

import anyio
from afya_mcp import db, workflow
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from . import helpers
from .agent import Agent
from .demo_scenario import SCENARIOS, birth_date
from .deps import User, current_user, demo_mode, get_agent, get_gateway
from .errors import ERROR_RESPONSES, ApiError
from .mcp_client import Gateway
from .schemas import DemoNextOut, DemoScenarioIn, DemoVisitOut


def require_demo_mode() -> None:
    if not demo_mode():
        raise HTTPException(status_code=404, detail="not found")


router = APIRouter(tags=["demo"], dependencies=[Depends(require_demo_mode)])
DEMO_ACTOR = "system"   # seeded data (record_vitals doc); who clicked is in the demo_scenario audit row
DEMO_ROLES = ("nurse", "clinician")


def demo_user(user: User = Depends(current_user)) -> User:
    """A signed-in nurse or clinician: a manager reads only (403, audited as demo_scenario_refused, like POST /vitals).
    A plain `def`: FastAPI runs it in a worker thread, so the database write does not block the event loop."""
    if user.role not in DEMO_ROLES:
        with db.connect() as conn:
            workflow._audit(conn, "demo_scenario_refused", user.id, None, {"role": user.role})
        raise ApiError(403, "only a nurse or clinician can run the demo scenario")
    return user


async def _audit_click(user: User, action: str, visit_id: str | None, **payload: Any) -> None:
    """One demo_scenario audit row per click, actor = the signed-in user (auth demo_switcher)."""
    def write() -> None:
        with db.connect() as conn:
            workflow._audit(conn, "demo_scenario", user.id, visit_id, {"action": action, **payload})
    await anyio.to_thread.run_sync(write)


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
async def load_scenario(background: BackgroundTasks, body: DemoScenarioIn | None = None,
                        user: User = Depends(demo_user), gateway: Gateway = Depends(get_gateway),
                        agent: Agent = Depends(get_agent)) -> DemoVisitOut:
    """Load the P-014 scenario: synthetic patient and a fresh visit confirmed YELLOW, plus the first reading
    (scored YELLOW). Loading again finishes the previous demo visit and starts a new one."""
    name = (body or DemoScenarioIn()).name
    sc = SCENARIOS[name]
    try:
        seeded = await gateway.act("seed_demo_visit", {
            "label": sc["label"], "birth_date": birth_date(sc["age_years"]),
            "arrived_minutes_ago": sc["arrived_minutes_ago"], "confirmed_colour": sc["confirmed_colour"],
            "actor": DEMO_ACTOR})
    except Exception as e:
        raise helpers.tool_error(e) from e
    if seeded["status"] != "seeded":
        raise ApiError(409, f"the scenario could not be loaded ({seeded.get('reason', seeded['status'])})")
    obs = await _add_reading(gateway, seeded["visit_id"], 1, sc["readings"][0])
    await _audit_click(user, "load", seeded["visit_id"], scenario=name, obs_id=obs)
    background.add_task(agent.run_event, seeded["visit_id"], obs, DEMO_ACTOR)   # logged only: same colour
    return DemoVisitOut(visit_id=seeded["visit_id"])


@router.post("/demo/scenario/next", response_model=DemoNextOut, responses=ERROR_RESPONSES)
async def next_reading(background: BackgroundTasks, user: User = Depends(demo_user),
                       gateway: Gateway = Depends(get_gateway), agent: Agent = Depends(get_agent)) -> DemoNextOut:
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
    obs = await _add_reading(gateway, visit["visit_id"], n + 1, sc["readings"][n])
    await _audit_click(user, "next", visit["visit_id"], scenario="p014", reading=n + 1, obs_id=obs)
    background.add_task(agent.run_event, visit["visit_id"], obs, DEMO_ACTOR)   # the agent run, as after POST /vitals
    return DemoNextOut(obs_id=obs)
