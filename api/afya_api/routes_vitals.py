"""E6-1b: POST /vitals. The reading is saved by afya-mcp (act tool record_vitals) with the signed-in user as actor."""
from __future__ import annotations

from afya_mcp import workflow
from fastapi import APIRouter, BackgroundTasks, Depends

from . import helpers
from .agent import Agent
from .deps import User, current_user, get_agent, get_gateway
from .errors import ERROR_RESPONSES, ApiError
from .mcp_client import Gateway
from .schemas import VitalsIn, VitalsOut

router = APIRouter(tags=["vitals"])
INPUTS = ("resp_rate", "heart_rate", "systolic_bp", "temperature", "spo2", "mobility", "consciousness", "trauma")


@router.post("/vitals", response_model=VitalsOut, response_model_exclude_none=True, responses=ERROR_RESPONSES)
async def post_vitals(body: VitalsIn, background: BackgroundTasks, user: User = Depends(current_user),
                      gateway: Gateway = Depends(get_gateway), agent: Agent = Depends(get_agent)) -> VitalsOut:
    """Save one reading. 200 saved, 200 remeasure (impossible value, nothing saved), 422 invalid, 403 for a manager.
    A retry with the same idempotency_key returns the same observation_id. The tool is called for every role so that
    a manager's refusal is audited by afya-mcp (record_vitals_refused). A saved reading starts the agent's run
    (E5-2) in the background, after this answer is sent; run_id names it."""
    values = {name: getattr(body, name) for name in INPUTS if getattr(body, name) is not None}
    args = {"visit_id": body.visit_id, "values": values, "idempotency_key": body.idempotency_key, "actor": user.id,
            "complaint": body.complaint}
    try:
        out = await gateway.act("record_vitals", args)
    except Exception as e:
        raise helpers.tool_error(e, "only a nurse or clinician can enter vitals") from e
    if out["status"] == "invalid":
        raise ApiError(422, "the reading is not valid", out["problems"])
    if out["status"] == "remeasure":
        return VitalsOut(status="remeasure", problems=out["problems"])
    obs = workflow.obs_ref(out["observation_id"])
    background.add_task(agent.run_event, body.visit_id, obs, user.id)
    return VitalsOut(status="saved", observation_id=obs, run_id=workflow.run_id_for(body.visit_id, obs))
