"""E5-4: investigate, model call B (architecture section 4 and Appendix B).

A bounded, read-only tool loop: the model gets code-built facts (record ids, TEWS, the per-input changes, the trigger
decided by code, validated sign CODES; never the complaint or a quote, never FHIR free text) and may call at most
4 read-only tools, then `submit_decision`. The tools are wrappers that inject the visit and trim results to codes,
values, units, times and ids:

    fhir_search, fhir_read          -> the borrowed WSO2 server's `search` / `read` (Observations of this visit only)
    get_queue_state, check_deterioration, compute_tews (earlier readings only) -> afya-mcp /read, with the run_id

The ToolNode is built from the SAME list that is bound to the model (`read_only_tools`), so a forged call to any
other tool (e.g. a write tool) is refused by the ToolNode and logged; write tools are never reachable from here.
Cited ids that no tool returned in this run are rejected. The loop is a LangGraph subgraph with recursion limit 12.
What the model's decision may change is decided in decision.py (E5-5: it can only add).
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from .model import ModelUnavailable
from .steps import write as write_step

MAX_CALLS = 4               # read-only tool calls per run
MAX_TURNS = MAX_CALLS + 1   # model turns: one per tool round, plus the final submit_decision
RECURSION_LIMIT = 12
MAX_COUNT = 5
PANEL = "85353-1"
LOINC_ALLOW = {"9279-1": "resp_rate", "8867-4": "heart_rate", "8480-6": "systolic_bp", "8310-5": "temperature",
               "59408-5": "spo2"}
# N1 / security audit: the unit given to the model is a UCUM CODE from this allow-list per LOINC code, never the
# FHIR `unit` display text (free text anyone with FHIR write access could fill).
UCUM = "http://unitsofmeasure.org"
UNIT_ALLOW = {"9279-1": {"/min"}, "8867-4": {"/min"}, "8480-6": {"mm[Hg]"}, "8310-5": {"Cel", "[degF]"},
              "59408-5": {"%"}}
ACTIONS = ("propose", "propose_and_remeasure", "request_missing_value")
ID = re.compile(r"^(Observation|Encounter)/[A-Za-z0-9.-]{1,64}$")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")

PROMPT = """You review a second-look flag for a triage nurse. Fixed code has ALREADY decided that a proposal will \
be shown to the nurse (the trigger below). You cannot cancel it and you can never lower the colour.
You may only: ask for a re-measure (action "propose_and_remeasure"), add one of the listed sign codes as an extra \
trigger, or ask for a missing value (action "request_missing_value" with missing_input = the input name).
Otherwise use action "propose".
Use at most 4 read-only tool calls if they help (earlier readings, the queue), then call submit_decision once.
Rationale (at most 300 characters): describe only measured changes and SATS signs, with their record ids. Never name a \
condition, cause, drug, dose or treatment. Cite only record ids that the facts or the tools gave you."""


class DecisionArgs(BaseModel):
    action: Literal["propose", "propose_and_remeasure", "request_missing_value"]
    extra_triggers: list[str] = Field(default_factory=list, max_length=5)
    rationale: str = Field(default="", max_length=600)
    cited_ids: list[str] = Field(default_factory=list, max_length=20)
    missing_input: str | None = None


class CountArgs(BaseModel):
    count: int = Field(default=5, ge=1, le=MAX_COUNT, description="how many readings, newest first (max 5)")


class ObsArgs(BaseModel):
    observation_id: str = Field(description='a record id such as "Observation/123"')


class NoArgs(BaseModel):
    pass


def ids_in(value: Any) -> set[str]:
    """Every record id ("Observation/..", "Encounter/..") in a tool result."""
    out: set[str] = set()
    if isinstance(value, str):
        if ID.match(value):
            out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            out |= ids_in(v)
    elif isinstance(value, list):
        for v in value:
            out |= ids_in(v)
    return out


def trim_observation(r: dict[str, Any]) -> dict[str, Any] | None:
    """FHIR Observation -> {id, time, values: [{code, value, unit}]} with LOINC allow-listed quantities only.
    No text, no identifiers, no subject: nothing a patient or nurse typed reaches the model."""
    if r.get("resourceType") != "Observation" or not any(c.get("code") == PANEL
                                                          for c in r.get("code", {}).get("coding", [])):
        return None
    values = []
    for comp in r.get("component", []):
        code = next((c["code"] for c in comp.get("code", {}).get("coding", [])
                     if c.get("system") == "http://loinc.org" and c.get("code") in LOINC_ALLOW), None)
        q = comp.get("valueQuantity")
        if code and isinstance(q, dict) and isinstance(q.get("value"), (int, float)) \
                and not isinstance(q.get("value"), bool):
            unit = q.get("code") if q.get("system") in (UCUM, None) and q.get("code") in UNIT_ALLOW[code] else None
            values.append({"code": code, "value": q["value"], "unit": unit})
    return {"id": f"Observation/{r.get('id')}", "time": r.get("effectiveDateTime"), "values": values}


def trim_tews(out: dict[str, Any]) -> dict[str, Any]:
    return {k: out.get(k) for k in ("status", "observation_id", "tews", "colour", "complete", "missing", "points")}


def trim_deterioration(out: dict[str, Any]) -> dict[str, Any]:
    if out.get("status") != "checked":
        return {"status": out.get("status")}
    t = out.get("trigger") or {}
    return {"status": "checked", "confirmed_colour": out.get("confirmed_colour"),
            "latest": {k: out["latest"].get(k) for k in ("observation_id", "tews", "colour", "complete", "missing")},
            "previous": {k: out["previous"].get(k) for k in ("observation_id", "tews", "colour")}
            if out.get("previous") else None,
            "changes": out.get("changes", []), "trigger": {k: t.get(k) for k in ("kind", "from", "to", "propose")}}


def trim_queue(out: dict[str, Any], visit_id: str) -> dict[str, Any]:
    p = next((x for x in out.get("patients", []) if x.get("visit_id") == visit_id), None)
    entry = None if p is None else {
        "visit_id": visit_id, "confirmed_colour": p.get("confirmed_colour"), "minutes_waited": p.get("minutes_waited"),
        "target_minutes": p.get("target_minutes"), "over_target_minutes": p.get("over_target_minutes"),
        "last_reading": p.get("last_reading"), "pending_proposals": p.get("pending_proposals"),
        "recheck": {k: (p.get("recheck") or {}).get(k) for k in ("interval_minutes", "overdue", "overdue_minutes")}}
    props = [{k: x.get(k) for k in ("status", "to_colour", "age_minutes", "obs_id")}
             for x in out.get("proposals") or [] if x.get("visit_id") == visit_id]
    return {"status": "ok", "patients_waiting": len(out.get("patients", [])), "this_visit": entry, "proposals": props}


def read_only_tools(ctx: Any, run_id: str, visit_id: str, obs_id: str, seen: set[str]) -> list[BaseTool]:
    """The ONLY tools the model gets, all read-only; the visit is injected. `seen` collects the record ids the tools
    return (cited ids outside it are rejected)."""
    gw = ctx.gateway
    current = f"Observation/{obs_id}"

    def done(result: dict[str, Any]) -> str:
        seen.update(ids_in(result))
        return json.dumps(result, default=str)

    async def fhir_search(count: int = 5) -> str:
        params = {"encounter": f"Encounter/{visit_id}", "code": f"http://loinc.org|{PANEL}", "_sort": "-date",
                  "_count": str(min(max(int(count), 1), MAX_COUNT))}
        try:
            bundle = await gw.wso2("search", {"type": "Observation", "searchParam": params})
        except Exception as e:  # noqa: BLE001
            await write_step(run_id, visit_id, "tool", "search", f"type=Observation, encounter=Encounter/{visit_id}",
                             f"error: {type(e).__name__}", server="borrowed")
            return json.dumps({"error": "search failed"})
        rows = [x for x in (trim_observation(e.get("resource", {})) for e in bundle.get("entry", [])) if x]
        await write_step(run_id, visit_id, "tool", "search", f"type=Observation, encounter=Encounter/{visit_id}",
                         f"{len(rows)} readings", server="borrowed", cited_ids=[r["id"] for r in rows])
        return done({"readings": rows})

    async def fhir_read(observation_id: str) -> str:
        oid = observation_id.split("/")[-1]
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,64}", oid):
            return json.dumps({"error": "not a record id"})
        try:
            r = await gw.wso2("read", {"type": "Observation", "id": oid})
        except Exception as e:  # noqa: BLE001
            await write_step(run_id, visit_id, "tool", "read", f"Observation/{oid}", f"error: {type(e).__name__}",
                             server="borrowed")
            return json.dumps({"error": "read failed"})
        if (r.get("encounter") or {}).get("reference") != f"Encounter/{visit_id}":
            await write_step(run_id, visit_id, "tool", "read", f"Observation/{oid}", "refused: not this visit",
                             server="borrowed")
            return json.dumps({"error": "that record is not a reading of this visit"})
        row = trim_observation(r)
        await write_step(run_id, visit_id, "tool", "read", f"Observation/{oid}",
                         "1 reading" if row else "not a reading", server="borrowed",
                         cited_ids=[row["id"]] if row else [])
        return done({"reading": row})

    async def get_queue_state() -> str:
        try:
            out = await gw.read("get_queue_state", {"run_id": run_id})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"get_queue_state failed ({type(e).__name__})"})
        return done(trim_queue(out, visit_id))

    async def check_deterioration() -> str:
        try:
            out = await gw.read("check_deterioration", {"visit_id": visit_id, "run_id": run_id})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"check_deterioration failed ({type(e).__name__})"})
        return done(trim_deterioration(out))

    async def compute_tews(observation_id: str) -> str:
        ref = "Observation/" + observation_id.split("/")[-1]
        if ref == current or ref not in seen:
            return json.dumps({"error": "only earlier readings of this visit that a tool has returned"})
        try:
            out = await gw.read("compute_tews", {"observation_id": ref, "run_id": run_id})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"compute_tews failed ({type(e).__name__})"})
        return done(trim_tews(out))

    async def submit_decision(action: str, extra_triggers: list[str] | None = None, rationale: str = "",
                              cited_ids: list[str] | None = None, missing_input: str | None = None) -> str:
        return json.dumps({"status": "decision recorded"})

    t = StructuredTool.from_function
    return [
        t(coroutine=fhir_search, name="fhir_search", args_schema=CountArgs,
          description="Earlier vital-sign readings of this visit (FHIR, read-only), newest first: id, time, values."),
        t(coroutine=fhir_read, name="fhir_read", args_schema=ObsArgs,
          description="One reading of this visit by record id (FHIR, read-only): id, time, values."),
        t(coroutine=get_queue_state, name="get_queue_state", args_schema=NoArgs,
          description="This visit in the waiting room: minutes waited vs the SATS target, re-check due, proposals."),
        t(coroutine=check_deterioration, name="check_deterioration", args_schema=NoArgs,
          description="Latest vs previous reading of this visit with per-input point changes and record ids."),
        t(coroutine=compute_tews, name="compute_tews", args_schema=ObsArgs,
          description="Score an EARLIER reading of this visit (record id from another tool). Fixed code scores it."),
        t(coroutine=submit_decision, name="submit_decision", args_schema=DecisionArgs,
          description="Finish: action, extra_triggers (sign codes from the facts), rationale, cited_ids, "
                      "missing_input (only with request_missing_value)."),
    ]


def to_ollama(messages: list[AnyMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            out.append({"role": "system", "content": m.content})
        elif isinstance(m, HumanMessage):
            out.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            msg: dict[str, Any] = {"role": "assistant", "content": m.content or ""}
            if m.tool_calls:
                msg["tool_calls"] = [{"id": c.get("id"), "function": {"name": c["name"], "arguments": c["args"]}}
                                     for c in m.tool_calls]
            out.append(msg)
        elif isinstance(m, ToolMessage):
            out.append({"role": "tool", "content": m.content, "tool_name": m.name or "",
                        "tool_call_id": m.tool_call_id})
    return out


class LoopState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    turns: int
    reads: int
    stop: str | None


def facts_message(facts: dict[str, Any]) -> str:
    """Code-built facts only: ids, codes and numbers. No complaint, no quote, no FHIR text."""
    sc, det, trig = facts["score"], facts["det"], facts["trigger"]
    prev = det.get("previous")
    return json.dumps({
        "visit_id": f"Encounter/{facts['visit_id']}",
        "reading": {"id": sc["observation_id"], "tews": sc["tews"], "colour": sc["colour"],
                    "complete": sc["complete"], "missing_inputs": sc["missing"]},
        "previous_reading": {"id": prev["observation_id"], "tews": prev["tews"], "colour": prev["colour"]}
        if prev else None,
        "confirmed_colour": det.get("confirmed_colour"),
        "changes": det.get("changes", []),
        "trigger": {"kind": trig["kind"], "from": trig["from"], "to": trig["to"]},
        "validated_sign_codes": facts["sign_codes"],
    }, default=str)


async def investigate(ctx: Any, run_id: str, facts: dict[str, Any]) -> dict[str, Any]:
    """Returns {action, extra_triggers, missing_input, rationale, cited_ids, rejected_ids, seen_ids, model}.
    Never raises: model down, timeout, no decision or a broken loop all mean the code-built proposal stands."""
    visit_id, obs_id = facts["visit_id"], facts["obs_id"]
    seen: set[str] = ids_in({"s": facts["score"], "d": facts["det"]})   # compute_tews / check_deterioration ran
    tools = read_only_tools(ctx, run_id, visit_id, obs_id, seen)
    names = {t.name for t in tools}
    bound = [convert_to_openai_tool(t) for t in tools]   # the model is bound to exactly this list...
    tool_node = ToolNode(tools)                           # ...and the ToolNode runs exactly this list
    model = ctx.model
    seed = getattr(ctx, "seed", None)
    info = {**await model.describe(seed), "temperature": model.s.temperatures["investigate"]}

    async def agent(s: LoopState) -> dict[str, Any]:
        turn = s.get("turns", 0)
        try:
            reply = await model.call(to_ollama(s["messages"]), "investigate", deadline=ctx.deadline, tools=bound,
                                     seed=seed)
        except ModelUnavailable as e:
            await write_step(run_id, visit_id, "model", "investigate", f"turn {turn + 1}",
                             f"model unavailable ({e.reason}): rules only", model=info, unavailable=e.reason)
            return {"stop": f"unavailable:{e.reason}", "turns": turn + 1}
        budget = MAX_CALLS - s.get("reads", 0)
        calls, dropped, reads = [], 0, 0
        for i, c in enumerate(reply.tool_calls):
            if c["name"] != "submit_decision":
                if reads >= budget:
                    dropped += 1
                    continue
                reads += 1
            calls.append({"name": c["name"], "args": c["args"], "id": f"call_{turn}_{i}", "type": "tool_call"})
        for c in calls:
            if c["name"] not in names:   # forged call: the ToolNode below refuses it; log it here
                await write_step(run_id, visit_id, "tool", c["name"] if NAME.match(c["name"]) else "unknown",
                                 "-", "refused: not an offered tool (read-only list)")
        summary = ", ".join(c["name"] if c["name"] in names else "refused tool" for c in calls) or "no tool call"
        await write_step(run_id, visit_id, "model", "investigate", f"turn {turn + 1}",
                         summary + (f"; {dropped} call(s) over the limit of {MAX_CALLS} dropped" if dropped else ""),
                         latency_ms=reply.latency_ms, tokens_in=reply.tokens_in, tokens_out=reply.tokens_out,
                         cost_usd=reply.cost_usd, model={**info, "load_ms": reply.load_ms, "eval_ms": reply.eval_ms,
                                                           "served_by": reply.provider})
        return {"messages": [AIMessage(content=reply.content or "", tool_calls=calls)], "turns": turn + 1,
                "reads": s.get("reads", 0) + reads, "stop": None if calls else "no decision"}

    def after_agent(s: LoopState) -> str:
        return END if s.get("stop") else "tools"

    def after_tools(s: LoopState) -> str:
        if _decision(s["messages"]) is not None or s.get("turns", 0) >= MAX_TURNS:
            return END
        return "agent"

    g = StateGraph(LoopState)
    g.add_node("agent", agent)
    g.add_node("tools", tool_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", after_agent, ["tools", END])
    g.add_conditional_edges("tools", after_tools, ["agent", END])
    loop = g.compile(checkpointer=False)
    start = [SystemMessage(PROMPT), HumanMessage(facts_message(facts))]
    try:
        final = await loop.ainvoke({"messages": start, "turns": 0, "reads": 0, "stop": None},
                                   {"recursion_limit": RECURSION_LIMIT})
    except GraphRecursionError:
        final = {"messages": start, "stop": "recursion_limit"}
    except Exception as e:  # noqa: BLE001 - B2: a tool or the loop broke: the code-built proposal stands
        await write_step(run_id, visit_id, "model", "investigate", "-",
                         "model unavailable (invalid_response): rules only", unavailable="invalid_response",
                         error=type(e).__name__)
        final = {"messages": start, "stop": "unavailable:invalid_response"}
    dec = _decision(final["messages"])
    base = {"seen_ids": sorted(seen), "extra_triggers": [], "missing_input": None, "rationale": None,
            "cited_ids": [], "rejected_ids": 0}
    stop = final.get("stop")
    if dec is None:
        return {**base, "action": "propose", "model": stop or "no decision"}
    cited = [c for c in dec.cited_ids if isinstance(c, str)]
    ok = [c for c in cited if c in seen]
    return {**base, "action": dec.action, "extra_triggers": list(dec.extra_triggers),
            "missing_input": dec.missing_input, "rationale": dec.rationale or None, "cited_ids": ok,
            "rejected_ids": len(cited) - len(ok), "model": "ok"}


def no_decision(model: str) -> dict[str, Any]:
    """investigate's result when it did not run or broke: the code-built proposal stands unchanged."""
    return {"seen_ids": [], "extra_triggers": [], "missing_input": None, "rationale": None, "cited_ids": [],
            "rejected_ids": 0, "action": "propose", "model": model}


def _decision(messages: list[AnyMessage]) -> DecisionArgs | None:
    """The last submit_decision call that the ToolNode accepted (its arguments passed the schema)."""
    ok_ids = {m.tool_call_id for m in messages if isinstance(m, ToolMessage) and m.name == "submit_decision"
              and m.status == "success"}
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            for c in reversed(m.tool_calls):
                if c["name"] == "submit_decision" and c["id"] in ok_ids:
                    try:
                        return DecisionArgs(**c["args"])
                    except (TypeError, ValueError):
                        return None
    return None
