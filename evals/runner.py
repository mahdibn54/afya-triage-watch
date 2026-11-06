"""Live trial runner (groups B and C), host-side against the real stack: afya-mcp, WSO2, HAPI, Postgres and Ollama.

One trial = a fresh synthetic visit, the case's readings saved in order (each reading starts the agent run as in
production), the LAST reading's run is the one scored. Nothing is approved: the harness never clicks, so any Flag or
command that appears is an ungated action. Pending proposals are rejected afterwards ("eval cleanup") so the demo
queue is not polluted; that happens after everything is logged.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from afya_api.agent import Agent
from afya_api.demo_scenario import birth_date
from afya_api.model import Model, ModelSettings, backend_for
from afya_mcp import db, workflow

from .cases import Case
from .host_gateway import HostGateway

RULES_ONLY = "rules-only"
SCHEMA = 1
ACT_AFTER_APPROVAL = ("raise_recheck_flag", "command_done", "proposal_approved")


def _commit() -> str:
    try:
        root = Path(__file__).resolve().parent.parent
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True,
                             timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "api", "mcp", "rules"], cwd=root, capture_output=True,
                               text=True, timeout=5).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


async def _no_hook(*_a: Any, **_k: Any) -> None:
    """The eval does not send RED/ORANGE reminders to the live queue."""


def _fetch(run_id: str, visit_id: str, obs_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[str]]:
    with db.connect() as c:
        rows = c.execute("SELECT id, kind, payload FROM audit_log WHERE run_id = %s ORDER BY id", (run_id,)).fetchall()
        prop = c.execute("SELECT payload, status FROM proposals WHERE visit_id = %s AND obs_id = %s", (visit_id, obs_id)
                         ).fetchone()
        ungated = c.execute("SELECT kind FROM audit_log WHERE visit_id = %s AND kind = ANY(%s) ORDER BY id",
                            (visit_id, list(ACT_AFTER_APPROVAL))).fetchall()
        cmds = c.execute("SELECT count(*) AS n FROM commands WHERE visit_id = %s", (visit_id,)).fetchone()
    found = [r["kind"] for r in ungated] + (["command_row"] * cmds["n"])
    return rows, ({"payload": prop["payload"], "status": prop["status"]} if prop else None), found


def _cleanup(visit_id: str) -> None:
    with db.connect() as c:
        pending = c.execute("SELECT id FROM proposals WHERE visit_id = %s AND status = 'pending'",
                            (visit_id,)).fetchall()
        for p in pending:
            workflow.reject_proposal(c, str(p["id"]), "nurse-a", "eval cleanup (synthetic visit)")


def compact_trace(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The run's audit rows as the trace the metrics read, plus numbers summed over the model calls."""
    trace: list[dict[str, Any]] = []
    tin = tout = 0
    lat = 0.0
    cost = 0.0
    digest = None
    unavailable: str | None = None
    for r in rows:
        p = r["payload"]
        if r["kind"] == "agent_step":
            trace.append({"name": p["name"], "step_kind": p["step_kind"], "server": p.get("server"),
                          "args": p.get("args_summary"), "result": p.get("result_summary"),
                          "latency_ms": p.get("latency_ms"), "tokens_in": p.get("tokens_in"),
                          "tokens_out": p.get("tokens_out"), "cost_usd": p.get("cost_usd"),
                          "cited_ids": p.get("cited_ids") or []})
            tin += p.get("tokens_in") or 0
            tout += p.get("tokens_out") or 0
            cost += p.get("cost_usd") or 0
            if p["step_kind"] == "model":
                lat += p.get("latency_ms") or 0
                digest = digest or (p.get("model") or {}).get("digest")
                unavailable = unavailable or p.get("unavailable")
        else:
            out = p.get("output") or {}
            trace.append({"name": r["kind"], "step_kind": "tool", "server": "ours",
                          "args": json.dumps(p.get("inputs"))[:160], "result": str(out.get("status")),
                          "latency_ms": p.get("latency_ms"), "tokens_in": None, "tokens_out": None,
                          "cost_usd": None, "cited_ids": []})
    return trace, {"tokens_in": tin, "tokens_out": tout, "model_latency_ms": round(lat, 1), "cost_usd": cost,
                   "model_digest": digest, "model_unavailable": unavailable}


def _card(payload: dict[str, Any]) -> dict[str, Any]:
    keep = ("to_colour", "current_colour", "tews_before", "tews_after", "reasons", "rationale", "rationale_source",
            "notices", "agent_action", "missing_input", "signs_verdict", "cited_obs_ids")
    card = {k: payload.get(k) for k in keep}
    card["signs"] = [{k: s.get(k) for k in ("code", "status", "source", "quote", "reason")}
                     for s in payload.get("signs", [])]
    return card


async def _put_note(client: httpx.AsyncClient, hapi: str, obs_ref: str, text: str) -> None:
    oid = obs_ref.split("/")[-1]
    r = await client.get(f"{hapi}/Observation/{oid}")
    r.raise_for_status()
    res = r.json()
    res["note"] = [{"text": text}]
    (await client.put(f"{hapi}/Observation/{oid}", json=res)).raise_for_status()


async def run_trial(case: Case, tag: str, group: str, run_index: int, settings: ModelSettings, set_name: str,
                    gw: HostGateway, batch: str, commit: str, cleanup: bool = True) -> dict[str, Any]:
    model = Model(backend_for(settings), settings, enabled=(group == "B"))
    agent = Agent(gw, model, on_proposal=_no_hook)
    trial: dict[str, Any] = {
        "schema": SCHEMA, "trial_id": f"{group}-{tag}-{case.id}-{run_index}", "batch": batch, "group": group,
        "model": tag, "set": set_name, "run_index": run_index, "case_id": case.id, "split": case.split,
        "tags": case.tags, "expected": case.expected, "code_commit": commit,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "settings": {"seed": settings.seed, "num_ctx": settings.num_ctx, "num_predict": settings.num_predict,
                     "top_p": settings.top_p, "top_k": settings.top_k, "temperatures": settings.temperatures},
        "proposal": None, "decision": None, "trace": [], "kept_signs": [], "ungated": [], "visit_obs_ids": [],
        "error": None, "run_status": None, "stop": None}
    label = f"EV-{case.id[:18]}-{uuid.uuid4().hex[:6]}"
    visit_id = None
    try:
        seeded = await gw.act("seed_demo_visit", {"label": label, "birth_date": birth_date(case.age_years),
                                                  "arrived_minutes_ago": case.arrived_minutes_ago,
                                                  "confirmed_colour": case.confirmed_colour, "actor": "system"})
        visit_id = seeded["visit_id"]
        trial["visit_label"] = label
        out: dict[str, Any] = {}
        obs_ids: list[str] = []
        wall = 0.0
        async with httpx.AsyncClient(timeout=30) as http:
            for i, rd in enumerate(case.readings):
                saved = await gw.act("record_vitals", {"visit_id": visit_id, "values": rd["values"],
                                                       "idempotency_key": f"ev-{uuid.uuid4().hex}", "actor": "nurse-a",
                                                       "complaint": rd.get("complaint")})
                if saved.get("status") != "saved":
                    trial["run_status"] = "input_refused"
                    trial["stop"] = f"record_vitals: {saved.get('status')}"
                    out = {}
                    obs_ids = []
                    break
                obs_ids.append(saved["observation_id"])
                last = i == len(case.readings) - 1
                if last and case.fhir_note:
                    await _put_note(http, os.environ["EVAL_HAPI_URL"], saved["observation_id"], case.fhir_note)
                t0 = time.perf_counter()
                out = await agent.run_event(visit_id, saved["observation_id"], "nurse-a")
                if last:
                    wall = (time.perf_counter() - t0) * 1000
        trial["visit_obs_ids"] = obs_ids
        trial["wall_ms"] = round(wall, 1)
        if obs_ids:
            run_id = out["run_id"]
            trial["run_id"] = run_id
            trial["run_status"] = out["status"]
            trial["stop"] = out.get("stop")
            rows, prop, ungated = await asyncio.to_thread(_fetch, run_id, visit_id, obs_ids[-1].split("/")[-1])
            trial["trace"], nums = compact_trace(rows)
            trial.update(nums)
            trial["ungated"] = ungated
            ms = next((r for r in rows if r["kind"] == "agent_step" and r["payload"]["name"] == "map_signs"), None)
            trial["kept_signs"] = list((ms or {"payload": {}})["payload"].get("kept") or [])
            if prop:
                trial["proposal"] = _card(prop["payload"])
                trial["proposal_status"] = prop["status"]
                sd = next((r for r in rows if r["kind"] == "agent_step" and r["payload"]["name"] == "submit_decision"),
                          None)
                if sd:
                    p = sd["payload"]
                    trial["decision"] = {k: p.get(k) for k in ("rationale_replaced", "rejected_cited_ids",
                                                               "model_decision", "ignored", "rationale_source",
                                                               "cited_ids")}
    except Exception as e:  # noqa: BLE001 - recorded as a failed trial; class name only, never a message or header
        trial["error"] = type(e).__name__
    finally:
        if cleanup and visit_id:
            try:
                await asyncio.to_thread(_cleanup, visit_id)
            except Exception as e:  # noqa: BLE001
                trial["cleanup_error"] = type(e).__name__
    trial["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return trial


def safe(tag: str) -> str:
    return "".join(c if c.isalnum() or c in "-." else "_" for c in tag)


async def run_all(cases: list[Case], models: list[str], runs: int, rules_only_runs: int, out_dir: Path, set_name: str,
                  ollama_url: str, cleanup: bool = True, log: Any = print) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    gw = HostGateway()
    batch = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    commit = _commit()
    written: list[Path] = []
    plan = [(RULES_ONLY, "C", rules_only_runs)] if rules_only_runs else []
    plan += [(m, "B", runs) for m in models]
    for tag, group, n in plan:
        # a tag with a slash is an OpenRouter model id (E5-11), anything else an Ollama tag
        settings = ModelSettings(provider="openrouter" if "/" in tag else "ollama", base_url=ollama_url,
                                 model=RULES_ONLY if group == "C" else tag)
        if group == "B":
            warm = Model(backend_for(settings), settings)
            t = time.perf_counter()
            ok = await warm.warm_up()
            log(f"warm-up {tag}: {'ok' if ok else 'FAILED'} in {time.perf_counter() - t:.1f}s")
        path = out_dir / f"{batch}_{safe(set_name)}_{group}_{safe(tag)}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for i in range(1, n + 1):
                for case in cases:
                    tr = await run_trial(case, tag, group, i, settings, set_name, gw, batch, commit, cleanup)
                    f.write(json.dumps(tr, ensure_ascii=False, sort_keys=True) + "\n")
                    f.flush()
                    p = tr["proposal"]
                    log(f"{tr['trial_id']:<48} proposal={'-' if not p else p['to_colour']:<7} "
                        f"want={'-' if not case.expected['proposal'] else case.expected['to_colour']:<7} "
                        f"wall={tr.get('wall_ms') or 0:>8.0f}ms err={tr['error']}")
        written.append(path)
    return written
