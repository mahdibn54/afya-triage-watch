"""E5-2: the event run, one LangGraph thread per saved reading (architecture sections 4, 5 and 7).

    validate -> record -> score -> deteriorate -> map_signs -> trigger -> investigate -> proposal -> paused -> executor

- validate: the reading is still the visit's latest (a newer one gets its own run).
- record: the reading was saved by POST /vitals (afya-mcp record_vitals); this step loads its complaint (Postgres).
- score / deteriorate: afya-mcp read tools compute_tews and check_deterioration, called with the run_id (their audit
  rows are the trace steps).
- map_signs (model call A, E5-3), trigger (fixed code, rules.evaluate_trigger: the model cannot switch it off),
  investigate (model call B, read-only tool loop, E5-4).
- proposal: code builds the card (decision.py) and saves it with workflow.insert_proposal (dedup key = visit, trigger,
  hash of observation ids + sign codes + chart id); then `paused` calls interrupt(): nothing changes in the queue.
- executor: resumed by POST /proposals/{id}/approve with the command id; calls afya-mcp act raise_recheck_flag.

Thread id = run_id = "<visit>:<bare obs id>" (workflow.run_id_for); checkpoints live in Postgres schema lg
(AsyncPostgresSaver; tables created once by lg-init as the owner). Runs start in the background after POST /vitals
has answered. A run never raises to its caller; a failure is written to the trace.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from afya_mcp import db, rules, workflow
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from . import decision, executor, steps, watch
from . import investigate as inv
from . import signs as sg
from .mcp_client import Gateway, ToolRefused
from .model import Model

log = logging.getLogger("afya_api.agent")
RECURSION_LIMIT = 25   # the main graph has 10 nodes and no loop; the investigate loop has its own limit of 12


class RunState(TypedDict, total=False):
    run_id: str
    visit_id: str
    obs_id: str                 # bare Observation id (as in visits.latest_obs_id and proposals.obs_id)
    reading_at: str | None      # the reading's effectiveDateTime: tells a reused id after a FHIR reset apart (N7)
    actor: str                  # who entered the reading
    stop: str | None            # why the run ended early (None while it goes on)
    complaint: str | None
    reported_worsening: bool    # ticked with the reading: proposal even without a score rise (trigger nurse_reported)
    score: dict[str, Any]
    det: dict[str, Any]
    signs: dict[str, Any]
    trigger: dict[str, Any]
    decision: dict[str, Any]
    proposal_id: str | None
    command: dict[str, Any] | None
    result: dict[str, Any] | None


@dataclass
class RunContext:
    """Per-run objects that are not checkpointed: clients, the chart registry and the run's model deadline."""
    gateway: Gateway
    model: Model
    registry: list[dict[str, Any]]
    deadline: float
    run_id: str
    visit_id: str
    extra: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None     # the run's model seed (logged with each call)

    def chart(self, chart_id: str) -> dict[str, Any]:
        return next(c for c in self.registry if c["chart_id"] == chart_id)


def bare(ref: str) -> str:
    return [p for p in str(ref).split("/") if p][-1]


async def retry(fn: Callable[[], Awaitable[dict[str, Any]]], attempts: int = 3, delay: float = 0.5) -> dict[str, Any]:
    """FHIR or afya-mcp down: retry 3 times (architecture section 10), then let the run fail (it is traced)."""
    for i in range(attempts):
        try:
            return await fn()
        except ToolRefused:
            raise
        except Exception:
            if i == attempts - 1:
                raise
            await asyncio.sleep(delay * (i + 1))
    raise AssertionError("unreachable")


# ---------- database reads (worker threads) ----------

def _latest_obs(visit_id: str) -> str | None:
    with db.connect() as conn:
        row = conn.execute("SELECT latest_obs_id FROM visits WHERE id = %s", (visit_id,)).fetchone()
    return row["latest_obs_id"] if row else None


def _supersede(visit_id: str, obs_id: str) -> int:
    """E5-8: newer vitals make the pending proposals about older readings of this visit `superseded` (reviewed stays
    false: they show as "not reviewed" until a nurse acknowledges them). Their commands can no longer be claimed.
    record_vitals already does this in the transaction that moves latest_obs_id; the run repeats it (normally 0
    rows) and the proposal node re-checks after its insert, so a slow run of an older reading that finishes after a
    newer reading arrived leaves its proposal superseded, never pending."""
    with db.connect() as conn:
        return workflow.supersede_pending(conn, visit_id, obs_id)


def _reading_note(obs_id: str) -> tuple[str | None, bool]:
    """The reading's complaint and its reported-worsening tick (Postgres only)."""
    with db.connect() as conn:
        row = conn.execute("SELECT complaint, reported_worsening FROM readings WHERE obs_id = %s",
                           (obs_id,)).fetchone()
    return (row["complaint"], bool(row["reported_worsening"])) if row else (None, False)


def _save_proposal(visit_id: str, trigger: str, obs_id: str, ehash: str,
                   payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    with db.connect() as conn:
        p = workflow.insert_proposal(conn, visit_id, trigger, obs_id, ehash, payload)
        if p is not None:
            return p, True
        return conn.execute("SELECT * FROM proposals WHERE visit_id = %s AND trigger = %s AND evidence_hash = %s",
                            (visit_id, trigger, ehash)).fetchone(), False


def _open_notice(kind: str) -> bool:
    """An unacknowledged notification of this kind exists."""
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM notifications WHERE kind = %s AND acknowledged_at IS NULL LIMIT 1",
                            (kind,)).fetchone() is not None


def _latest_threads(limit: int) -> list[str]:
    """Run ids (= checkpoint thread ids) of visits' latest readings that have checkpoints, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT c.thread_id FROM lg.checkpoints c JOIN visits v ON c.thread_id = v.id || ':' || v.latest_obs_id "
            "WHERE c.checkpoint_ns = '' GROUP BY c.thread_id ORDER BY max(c.checkpoint_id) DESC LIMIT %s",
            (limit,)).fetchall()
    return [r["thread_id"] for r in rows]


def _command_run(command_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        return conn.execute("SELECT c.id, p.visit_id, p.obs_id FROM commands c "
                            "JOIN proposals p ON p.id = c.proposal_id WHERE c.id = %s", (command_id,)).fetchone()


async def reading_at(gateway: Gateway, visit_id: str, obs_id: str) -> str | None:
    """The reading's effectiveDateTime from the visit timeline (None if it cannot be read: never stops a run)."""
    try:
        tl = await gateway.ui("visit_timeline", {"visit_id": visit_id})
    except Exception:  # noqa: BLE001
        return None
    return next((r.get("at") for r in tl.get("readings", []) if r.get("obs_id") == f"Observation/{obs_id}"), None)


async def notify(ctx: RunContext, kind: str, proposal_id: str | None = None) -> dict[str, Any]:
    """afya-mcp act notify_staff as actor 'agent' with the run_id (fixed text; changes nothing in the queue)."""
    args: dict[str, Any] = {"kind": kind, "actor": "agent", "visit_id": ctx.visit_id, "run_id": ctx.run_id}
    if proposal_id:
        args["proposal_id"] = proposal_id
    try:
        return await ctx.gateway.act("notify_staff", args)
    except Exception as e:  # noqa: BLE001 - a reminder must never stop the run
        log.warning("notify_staff %s failed (%s)", kind, type(e).__name__)
        return {"status": "failed", "reason": type(e).__name__}


# ---------- the graph ----------

def build_graph(ctx: RunContext) -> StateGraph:
    run, visit = ctx.run_id, ctx.visit_id

    async def stop(name: str, why: str, args: str = "-") -> dict[str, Any]:
        await steps.write(run, visit, "gate", name, args, f"run stopped: {why}")
        return {"stop": why}

    async def validate(s: RunState) -> dict[str, Any]:
        latest = await asyncio.to_thread(_latest_obs, visit)
        args = f"observation_id=Observation/{s['obs_id']}"
        if latest is None:
            return await stop("validate", "unknown visit", args)
        if latest != s["obs_id"]:
            return await stop("validate", "a newer reading exists; it has its own run", args)
        await steps.write(run, visit, "gate", "validate", args, "latest reading of the visit",
                          cited_ids=[f"Observation/{s['obs_id']}"])
        return {"stop": None, "reading_at": await reading_at(ctx.gateway, visit, s["obs_id"])}

    async def record(s: RunState) -> dict[str, Any]:
        complaint, worse = await asyncio.to_thread(_reading_note, s["obs_id"])
        superseded = await asyncio.to_thread(_supersede, visit, s["obs_id"])
        note = f"{'with' if complaint else 'no'} complaint" + (", reported worse" if worse else "")
        await steps.write(run, visit, "tool", "record_vitals", f"observation_id=Observation/{s['obs_id']}",
                          f"saved by POST /vitals ({note})"
                          + (f"; {superseded} older proposal(s) superseded" if superseded else ""), server="ours",
                          cited_ids=[f"Observation/{s['obs_id']}"], superseded=superseded)
        return {"complaint": complaint, "reported_worsening": worse}

    async def score(s: RunState) -> dict[str, Any]:
        out = await retry(lambda: ctx.gateway.read("compute_tews", {"observation_id": f"Observation/{s['obs_id']}",
                                                                    "run_id": run}))
        if out.get("status") != "scored":   # no_chart (the queue shows the notice) or not_usable
            return {**await stop("score", str(out.get("status"))), "score": {"status": out.get("status")}}
        keep = ("status", "observation_id", "chart_id", "tews", "complete", "missing", "colour_by_tews", "signs",
                "colour", "points", "cited")
        return {"score": {k: out.get(k) for k in keep}}

    async def deteriorate(s: RunState) -> dict[str, Any]:
        out = await retry(lambda: ctx.gateway.read("check_deterioration", {"visit_id": visit, "run_id": run}))
        if out.get("status") != "checked":
            return {**await stop("deteriorate", str(out.get("status"))), "det": {"status": out.get("status")}}
        if bare(out["latest"]["observation_id"]) != s["obs_id"]:
            return {**await stop("deteriorate", "a newer reading exists; it has its own run"), "det": out}
        return {"det": out}

    async def map_signs(s: RunState) -> dict[str, Any]:
        chart = ctx.chart(s["score"]["chart_id"])
        try:
            out = await sg.map_signs(ctx, run, visit, s.get("complaint"), s["score"], chart)
        except Exception as e:  # noqa: BLE001 - B2: anything unexpected = model unavailable; the rules go on
            log.warning("map_signs failed in run %s (%s): rules only", run, type(e).__name__)
            await steps.write(run, visit, "model", "map_signs", "-", "model unavailable (invalid_response): rules only",
                              unavailable="invalid_response", error=type(e).__name__)
            out = sg.unavailable(s.get("complaint"), s["score"], chart, "invalid_response")
        return {"signs": out}

    async def trigger(s: RunState) -> dict[str, Any]:
        chart, sc, det = ctx.chart(s["score"]["chart_id"]), s["score"], s["det"]
        after = rules.Score(**{k: sc[k] for k in rules.Score.__dataclass_fields__})
        prev = det.get("previous")
        t = rules.evaluate_trigger(det.get("confirmed_colour"), after, s["signs"]["kept"], chart,
                                   nurse_reported_worsening=bool(s.get("reported_worsening")),
                                   previous_colour=prev["colour"] if prev else None)
        trig = {"kind": t.kind, "from": t.from_colour, "to": t.to_colour, "reasons": t.reasons}
        cited = [x for x in [prev and prev["observation_id"], sc["observation_id"]] if x]
        result = f"proposal: {t.kind}, {t.from_colour} to {t.to_colour}" if t.propose else f"log only: {t.reasons[0]}"
        await steps.write(run, visit, "decision", "trigger",
                          f"confirmed={det.get('confirmed_colour')}, colour={after.colour}, "
                          f"signs={','.join(s['signs']['kept']) or 'none'}"
                          f"{', reported worse' if s.get('reported_worsening') else ''}", result, cited_ids=cited)
        return {"trigger": trig, "stop": None if t.propose else "no trigger"}

    async def investigate(s: RunState) -> dict[str, Any]:
        signs_model = str(s["signs"].get("model", ""))
        if signs_model.startswith("unavailable:"):   # S2: the model did not answer map_signs: straight to rules only
            await steps.write(run, visit, "model", "investigate", "-",
                              f"skipped: model unavailable ({signs_model.split(':', 1)[1]}): rules only",
                              unavailable=signs_model.split(":", 1)[1])
            return {"decision": inv.no_decision(signs_model)}
        facts = {"visit_id": visit, "obs_id": s["obs_id"], "score": s["score"], "det": s["det"],
                 "trigger": s["trigger"], "sign_codes": s["signs"]["kept"]}
        try:
            return {"decision": await inv.investigate(ctx, run, facts)}
        except Exception as e:  # noqa: BLE001 - B2: the code-built proposal stands, with the "no model" notice
            log.warning("investigate failed in run %s (%s): rules only", run, type(e).__name__)
            await steps.write(run, visit, "model", "investigate", "-",
                              "model unavailable (invalid_response): rules only", unavailable="invalid_response",
                              error=type(e).__name__)
            return {"decision": inv.no_decision("unavailable:invalid_response")}

    async def proposal(s: RunState) -> dict[str, Any]:
        chart, det = ctx.chart(s["score"]["chart_id"]), s["det"]
        prev_ref = det["previous"]["observation_id"] if det.get("previous") else None
        timeline = await retry(lambda: ctx.gateway.ui("visit_timeline", {"visit_id": visit}))
        by_id = {r["obs_id"]: r for r in timeline.get("readings", [])}
        before, after = by_id.get(prev_ref), by_id.get(f"Observation/{s['obs_id']}")
        evidence = decision.evidence_rows(before, after)
        readings = [r for r in (before, after) if r]
        payload, sign_codes = decision.build_payload(s, chart, evidence, readings)
        obs_ids = [s["obs_id"], *([bare(prev_ref)] if prev_ref else [])]
        ehash = workflow.evidence_hash(obs_ids, sign_codes, chart["chart_id"])
        p, created = await asyncio.to_thread(_save_proposal, visit, s["trigger"]["kind"], s["obs_id"], ehash, payload)
        latest = await asyncio.to_thread(_latest_obs, visit)
        if latest and latest != s["obs_id"]:          # a newer reading arrived while this run was working
            await asyncio.to_thread(_supersede, visit, latest)
            p = {**p, "status": "superseded"}
        pid = str(p["id"])
        dec = s.get("decision") or {}
        rejected = dec.get("rejected_ids") or 0
        _merged, ignored = decision.merge_decision(dec, s["trigger"], s["score"], s["signs"]["kept"], chart)
        _text, _src, replaced = decision.rationale_text(dec.get("rationale"), "",
                                                        decision.facts_for(s, chart, evidence, readings))
        await steps.write(run, visit, "decision", "submit_decision",
                          f"{payload['agent_action']}: proposed {payload['to_colour']}",
                          f"proposal {'created' if created else 'already existed'} ({p['status']})"
                          + (f"; {rejected} cited id(s) rejected (no tool returned them)" if rejected else ""),
                          cited_ids=list(dict.fromkeys([*payload["cited_obs_ids"], *dec.get("cited_ids", [])])),
                          proposal_id=pid, rationale_source=payload["rationale_source"],
                          model_decision=dec.get("model"), rejected_cited_ids=rejected, ignored=ignored,
                          rationale_replaced=replaced)
        if p["status"] != "pending":
            return {"proposal_id": pid, "stop": f"proposal is {p['status']}"}
        await steps.write(run, visit, "gate", "paused_for_nurse", "waiting for a nurse or clinician",
                          "no change to the queue", proposal_id=pid)
        if created and payload["agent_action"] == "propose_and_remeasure":   # E5-5: the model may add a re-measure
            await notify(ctx, "remeasure", pid)
        await on_created(s, p, created)
        return {"proposal_id": pid}

    async def on_created(s: RunState, p: dict[str, Any], created: bool) -> None:
        hook = ctx.extra.get("on_proposal")
        if hook is not None and created:
            await hook(ctx, s, p)

    def paused(s: RunState) -> dict[str, Any]:
        resume = interrupt({"proposal_id": s["proposal_id"], "run_id": run})
        return {"command": resume}

    async def execute(s: RunState) -> dict[str, Any]:
        cmd = s["command"] or {}
        out = await executor.run_command(ctx.gateway, str(cmd.get("command_id")), str(cmd.get("actor")), run)
        return {"result": out}

    def go_on(next_node: str) -> Callable[[RunState], str]:
        return lambda s: END if s.get("stop") else next_node

    g = StateGraph(RunState)
    for name, fn in [("validate", validate), ("record", record), ("score", score), ("deteriorate", deteriorate),
                     ("map_signs", map_signs), ("trigger", trigger), ("investigate", investigate),
                     ("proposal", proposal), ("paused", paused), ("executor", execute)]:
        g.add_node(name, fn)
    g.add_edge(START, "validate")
    chain = ["validate", "record", "score", "deteriorate", "map_signs", "trigger", "investigate", "proposal",
             "paused", "executor"]
    for a, b in zip(chain, chain[1:], strict=False):
        if a in ("validate", "score", "deteriorate", "trigger", "proposal"):
            g.add_conditional_edges(a, go_on(b), [b, END])
        else:
            g.add_edge(a, b)
    g.add_edge("executor", END)
    return g


def database_url() -> str:
    return os.environ["DATABASE_URL"]


class Agent:
    """Starts event runs and resumes paused ones. One per process (deps.get_agent); tests build their own with a
    scripted model and the in-process gateway."""

    def __init__(self, gateway: Gateway, model: Model, registry: list[dict[str, Any]] | None = None,
                 on_proposal: Callable[..., Awaitable[None]] | None = None) -> None:
        self.gateway, self.model = gateway, model
        self.registry = registry if registry is not None else rules.load_registry()
        self.on_proposal = on_proposal or watch.notify_at_creation   # E5-7: RED/ORANGE notify at creation
        self._running: set[str] = set()
        if model.on_open is None:
            model.on_open = self._model_down

    async def _model_down(self, reason: str) -> None:
        """E5-10: the breaker just opened (2 failures in a row): one fixed-text notice for the nurses, not tied to a
        visit. Scoring, triggers and proposals go on with the rules only. At most one such notice is open at a time:
        while one is not acknowledged, a re-opening breaker adds nothing (B's review, item 1)."""
        try:
            if await asyncio.to_thread(_open_notice, "model_unavailable"):
                return
            await self.gateway.act("notify_staff", {"kind": "model_unavailable", "actor": "agent"})
        except Exception as e:  # noqa: BLE001
            log.warning("model_unavailable notice failed (%s)", type(e).__name__)

    async def _run_failed(self, run_id: str, visit_id: str) -> None:
        """S1: a run that stopped on an error tells the nurses (fixed text, tied to the visit)."""
        try:
            await self.gateway.act("notify_staff", {"kind": "agent_failed", "actor": "agent", "visit_id": visit_id,
                                                    "run_id": run_id})
        except Exception as e:  # noqa: BLE001
            log.warning("agent_failed notice for run %s failed (%s)", run_id, type(e).__name__)

    def _ctx(self, run_id: str, visit_id: str) -> RunContext:
        extra = {"on_proposal": self.on_proposal} if self.on_proposal else {}
        return RunContext(self.gateway, self.model, self.registry, self.model.deadline(), run_id, visit_id, extra,
                          self.model.s.run_seed(run_id))

    @contextlib.asynccontextmanager
    async def graph(self, ctx: RunContext) -> AsyncIterator[CompiledStateGraph]:
        """The compiled graph with a Postgres checkpointer on one short-lived connection (schema lg is on afya_app's
        search_path; the tables were created by lg-init)."""
        async with await AsyncConnection.connect(database_url(), autocommit=True, prepare_threshold=0,
                                                 row_factory=dict_row) as conn:
            yield build_graph(ctx).compile(checkpointer=AsyncPostgresSaver(conn))  # type: ignore[arg-type]

    @staticmethod
    def config(run_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": run_id}, "recursion_limit": RECURSION_LIMIT}

    async def run_event(self, visit_id: str, obs_id: str, actor: str = "agent") -> dict[str, Any]:
        """Run the graph for one saved reading, up to the pause. Never raises. A second start for the same reading
        (a retried POST /vitals) is a no-op when the run finished or is paused; a run that stopped half-way (a crash,
        an error, a restart) is RESUMED from its last checkpoint (S1). A failure is traced and the nurses get an
        `agent_failed` notice for the visit."""
        vid, oid = bare(visit_id), bare(obs_id)
        run_id = workflow.run_id_for(vid, oid)
        if run_id in self._running:
            return {"status": "running", "run_id": run_id}
        self._running.add(run_id)
        resumed = False
        try:
            ctx = self._ctx(run_id, vid)
            async with self.graph(ctx) as g:
                snap = await g.aget_state(self.config(run_id))
                old_at = snap.values.get("reading_at") if snap.values else None
                if old_at and old_at != await reading_at(self.gateway, vid, oid):
                    # N7: same ids, different reading (the FHIR server was reset, Postgres was not): a new run
                    await g.checkpointer.adelete_thread(run_id)   # type: ignore[union-attr]
                    await steps.write(run_id, vid, "gate", "stale_thread", f"reading at {old_at}",
                                      "old checkpoints of a reused record id removed; new run")
                    snap = await g.aget_state(self.config(run_id))
                if snap.values:
                    if not snap.next or snap.next == ("paused",):
                        return {"status": "already_ran", "run_id": run_id}
                    resumed = True
                    await steps.write(run_id, vid, "gate", "resume", f"from {snap.next[0]}",
                                      "unfinished run resumed from its last checkpoint")
                    out = await g.ainvoke(None, self.config(run_id))
                else:
                    out = await g.ainvoke({"run_id": run_id, "visit_id": vid, "obs_id": oid, "actor": actor,
                                           "stop": None}, self.config(run_id))
            return {"status": "paused" if out.get("proposal_id") and not out.get("stop") else "ended",
                    "run_id": run_id, "resumed": resumed, **{k: out.get(k) for k in ("stop", "proposal_id", "trigger")}}
        except Exception as e:  # noqa: BLE001
            log.exception("run %s failed", run_id)
            await steps.write(run_id, vid, "gate", "run_failed", "-", f"run stopped: {type(e).__name__}")
            await self._run_failed(run_id, vid)
            return {"status": "failed", "run_id": run_id, "reason": type(e).__name__}
        finally:
            self._running.discard(run_id)

    async def resume_unfinished(self, limit: int = 50, attempts: int = 5, delay: float = 3.0) -> list[dict[str, Any]]:
        """S1 startup sweep: resume every run of a visit's LATEST reading that stopped half-way (newest first, at
        most `limit`). Paused runs wait for a nurse and finished runs are left alone. Never raises."""
        for _ in range(attempts):
            try:
                threads = await asyncio.to_thread(_latest_threads, limit)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("unfinished-run sweep: database not ready (%s)", type(e).__name__)
                await asyncio.sleep(delay)
        else:
            return []
        out = []
        for run_id in threads:
            vid, oid = run_id.split(":", 1)
            try:
                ctx = self._ctx(run_id, vid)
                async with self.graph(ctx) as g:
                    snap = await g.aget_state(self.config(run_id))
                if not snap.values or not snap.next or snap.next == ("paused",):
                    continue
            except Exception as e:  # noqa: BLE001
                log.warning("unfinished-run sweep: %s not readable (%s)", run_id, type(e).__name__)
                continue
            out.append(await self.run_event(vid, oid))
        if out:
            log.info("unfinished-run sweep: %d run(s) resumed: %s", len(out), [r.get("status") for r in out])
        return out

    async def resume(self, command_id: str, actor: str) -> dict[str, Any]:
        """After approval: resume the paused run with the command id, so its executor node calls raise_recheck_flag.
        If there is no paused run for this proposal (it was created outside a run, or its checkpoint is gone), the
        same fixed executor runs directly. Never raises."""
        row = await asyncio.to_thread(_command_run, command_id)
        if row is None:
            return {"status": "not_found", "command_id": command_id}
        run_id = workflow.run_id_for(row["visit_id"], row["obs_id"])
        try:
            ctx = self._ctx(run_id, row["visit_id"])
            async with self.graph(ctx) as g:
                snap = await g.aget_state(self.config(run_id))
                if snap.next == ("paused",):
                    out = await g.ainvoke(Command(resume={"command_id": command_id, "actor": actor}),
                                          self.config(run_id))
                    if out.get("result"):
                        return out["result"]
        except Exception as e:  # noqa: BLE001
            log.warning("resume of run %s failed (%s); running the executor directly", run_id, type(e).__name__)
        return await executor.run_command(self.gateway, command_id, actor, run_id)   # S4: same actor, same run id
