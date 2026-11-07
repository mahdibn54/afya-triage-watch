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
from afya_api import model as model_mod
from afya_api.agent import Agent
from afya_api.demo_scenario import birth_date
from afya_api.model import GROQ_URL, OLLAMA_CLOUD_URL, Model, ModelSettings, backend_for
from afya_mcp import db, workflow

from .cases import Case
from .host_gateway import HostGateway

RULES_ONLY = "rules-only"
SCHEMA = 1
ACT_AFTER_APPROVAL = ("raise_recheck_flag", "command_done", "proposal_approved")
CLOUD = "ollama_cloud:"
GROQ = "groq:"
# The provider's plan limit was reached: the trial that hit it is not written as a result. `rate_limited` (a
# per-minute limit) is retried after a pause, the others stop the run (resume later with --resume <batch>).
LIMIT_REASONS = ("rate_limited", "daily_limit", "usage_limit")
RATE_RETRIES = 2
RATE_PAUSE_S = 65.0


def model_settings(tag: str, group: str, ollama_url: str) -> ModelSettings:
    """`ollama_cloud:<name>` is an Ollama Cloud model (name as GET https://ollama.com/api/tags lists it), a tag with a
    slash an OpenRouter id (E5-11), anything else a local Ollama tag. The keys are read from the environment by the
    backends; for Ollama Cloud, OLLAMA_API_KEY is taken from the repo's .env when it is not exported.
    `groq:<model id>` is a GroqCloud model (e.g. groq:openai/gpt-oss-120b), GROQ_API_KEY likewise."""
    if tag.startswith(GROQ):
        _key_from_dotenv("GROQ_API_KEY")
        name = tag[len(GROQ):]
        return ModelSettings(provider="groq", model=RULES_ONLY if group == "C" else name,
                             groq_url=os.environ.get("GROQ_BASE_URL", GROQ_URL).rstrip("/"),
                             reasoning_effort="low" if "gpt-oss" in name else None, num_predict=1024)
    if tag.startswith(CLOUD):
        _key_from_dotenv("OLLAMA_API_KEY")
        name = tag[len(CLOUD):]
        return ModelSettings(provider="ollama_cloud", model=RULES_ONLY if group == "C" else name,
                             ollama_cloud_url=os.environ.get("OLLAMA_CLOUD_BASE_URL", OLLAMA_CLOUD_URL).rstrip("/"),
                             think="low" if name.startswith("gpt-oss") else False, num_predict=1024)
    return ModelSettings(provider="openrouter" if "/" in tag else "ollama", base_url=ollama_url,
                         model=RULES_ONLY if group == "C" else tag)


def _key_from_dotenv(name: str) -> None:
    """Copy one key from the repo's .env into this process's environment (never printed or logged)."""
    if os.environ.get(name):
        return
    env = Path(__file__).resolve().parent.parent / ".env"
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == name and v.strip():
                os.environ[name] = v.strip().strip("'\"")
                return
    except OSError:
        return


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
    limit: str | None = None
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
                if p.get("unavailable") in LIMIT_REASONS:
                    limit = limit or p["unavailable"]
        else:
            out = p.get("output") or {}
            trace.append({"name": r["kind"], "step_kind": "tool", "server": "ours",
                          "args": json.dumps(p.get("inputs"))[:160], "result": str(out.get("status")),
                          "latency_ms": p.get("latency_ms"), "tokens_in": None, "tokens_out": None,
                          "cost_usd": None, "cited_ids": []})
    return trace, {"tokens_in": tin, "tokens_out": tout, "model_latency_ms": round(lat, 1), "cost_usd": cost,
                   "model_digest": digest, "model_unavailable": unavailable, "provider_limit": limit}


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


def _limit_of(tr: dict[str, Any]) -> str | None:
    lim = tr.get("provider_limit") or tr.get("model_unavailable")
    return lim if lim in LIMIT_REASONS else None


def _done_ids(path: Path) -> set[str]:
    """Trial ids already written to a log (resume)."""
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            done.add(json.loads(line)["trial_id"])
        except (ValueError, KeyError):
            continue
    return done


async def _groq_pause(log: Any) -> None:
    """Groq's free plan allows 8K tokens per minute: start each trial with a full per-minute budget (the
    x-ratelimit-reset-tokens of the last answer), so a trial is not cut short by pacing inside its run budget."""
    now = time.monotonic()
    wait = max((st.tokens_reset_at - now for st in model_mod._GROQ_RATES.values()), default=0.0)
    if wait > 0:
        log(f"pacing: {wait:.1f}s until the tokens-per-minute budget is full")
        await asyncio.sleep(wait)


async def run_all(cases: list[Case], models: list[str], runs: int, rules_only_runs: int, out_dir: Path, set_name: str,
                  ollama_url: str, cleanup: bool = True, log: Any = print, resume: str | None = None,
                  token_budget: int | None = None, sleep: Any = asyncio.sleep) -> list[Path]:
    """Trials run one after another. A provider limit never becomes a result: `rate_limited` is retried after a
    pause (RATE_RETRIES times), a daily/usage limit or the token budget (tokens in + out of this invocation, the
    next trial estimated as the largest so far) stops the run cleanly. `resume=<batch>` appends to that batch's logs
    and skips the trials already in them."""
    out_dir.mkdir(parents=True, exist_ok=True)
    gw = HostGateway()
    batch = resume or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    commit = _commit()
    written: list[Path] = []
    plan = [(RULES_ONLY, "C", rules_only_runs)] if rules_only_runs else []
    plan += [(m, "B", runs) for m in models]
    stopped = False
    used, biggest = 0, 0
    for tag, group, n in plan:
        if stopped:
            break
        settings = model_settings(tag, group, ollama_url)
        path = out_dir / f"{batch}_{safe(set_name)}_{group}_{safe(tag)}.jsonl"
        done = _done_ids(path)
        todo = [(i, c) for i in range(1, n + 1) for c in cases if f"{group}-{tag}-{c.id}-{i}" not in done]
        if done:
            log(f"resume {path.name}: {len(done)} trials already written, {len(todo)} to run")
        if not todo:
            if path.exists() and path.stat().st_size:
                written.append(path)
            continue
        groq = settings.provider == "groq" and group == "B"
        if group == "B":
            warm = Model(backend_for(settings), settings)
            t = time.perf_counter()
            ok = await warm.warm_up()
            log(f"warm-up {tag}: {'ok' if ok else 'FAILED'} in {time.perf_counter() - t:.1f}s")
            if warm.last in LIMIT_REASONS:
                log(f"STOPPED: {tag}: provider limit reached ({warm.last}) before the first trial; nothing written")
                break
        # trials run one after another (never concurrently): Ollama Cloud and Groq plans allow few requests
        with path.open("a", encoding="utf-8") as f:
            for i, case in todo:
                if token_budget is not None and group == "B" and used + biggest > token_budget:
                    log(f"STOPPED: token budget {token_budget} reached ({used} tokens used by this run); resume "
                        f"later with --resume {batch}")
                    stopped = True
                    break
                for attempt in range(RATE_RETRIES + 1):
                    if groq:
                        await _groq_pause(log)
                    tr = await run_trial(case, tag, group, i, settings, set_name, gw, batch, commit, cleanup)
                    lim = _limit_of(tr)
                    if lim == "rate_limited" and attempt < RATE_RETRIES:
                        log(f"{tr['trial_id']}: per-minute limit hit, not written; retry in {RATE_PAUSE_S:.0f}s")
                        await sleep(RATE_PAUSE_S)
                        continue
                    break
                spent = (tr.get("tokens_in") or 0) + (tr.get("tokens_out") or 0)
                used += spent
                if lim:
                    log(f"STOPPED: {tr['trial_id']}: provider limit reached ({lim}); this trial is not written, the "
                        f"trials before it are; resume later with --resume {batch}")
                    stopped = True
                    break
                biggest = max(biggest, spent)
                f.write(json.dumps(tr, ensure_ascii=False, sort_keys=True) + "\n")
                f.flush()
                p = tr["proposal"]
                log(f"{tr['trial_id']:<48} proposal={'-' if not p else p['to_colour']:<7} "
                    f"want={'-' if not case.expected['proposal'] else case.expected['to_colour']:<7} "
                    f"wall={tr.get('wall_ms') or 0:>8.0f}ms tokens={spent:>6} err={tr['error']}")
        if path.stat().st_size:
            written.append(path)
        else:
            path.unlink()
    return written
