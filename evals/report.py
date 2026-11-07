"""Rebuild the EVALS.md tables from the raw JSONL logs. Everything printed here is computed from logged trials; there
is no hand-typed number. `python -m evals tables` rewrites the block between the two markers in EVALS.md."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import metrics, stats

BEGIN = "<!-- BEGIN GENERATED TABLES (python -m evals tables; do not edit by hand) -->"
END = "<!-- END GENERATED TABLES -->"
RULES_ONLY = "rules-only"


def load_trials(runs_dir: str | Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted(Path(runs_dir).glob("*.jsonl")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                t = json.loads(line)
                t["_file"] = f.name
                t["_line"] = n
                out.append(t)
    return out


def cond(t: dict[str, Any]) -> str:
    """The condition a trial belongs to: its model, plus its batch when the same model ran in more than one batch
    on the same set (E12-5: two Groq runs at different commits are reported side by side, never merged)."""
    return t.get("_cond") or t["model"]


def label_conditions(trials: list[dict[str, Any]]) -> None:
    batches: dict[tuple[str, str], set[str]] = defaultdict(set)
    for t in trials:
        batches[(t["set"], t["model"])].add(str(t.get("batch")))
    for t in trials:
        many = len(batches[(t["set"], t["model"])]) > 1
        t["_cond"] = f"{t['model']} @ {t.get('batch')}" if many else t["model"]


def kn(pair: tuple[int, int]) -> str:
    return stats.fmt_kn(*pair)


def f0(x: float | None, unit: str = "") -> str:
    return "n/a" if x is None else f"{x:,.0f}{unit}"


def _cond_order(c: str) -> tuple[int, str]:
    return (1 if c.startswith(RULES_ONLY) else 0, c)


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def inventory(trials: list[dict[str, Any]]) -> str:
    g: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for t in trials:
        g[(t["set"], t["group"], t["model"], t["batch"], t["code_commit"])].append(t)
    rows = []
    for (s, grp, m, b, c), ts in sorted(g.items(), key=lambda kv: (kv[0][0], _cond_order(kv[0][2]), kv[0][3])):
        digests = sorted({t.get("model_digest")[:12] for t in ts if t.get("model_digest")})
        rows.append([f"`{s}`", grp, f"`{m}`", ", ".join(digests) or "-", b, f"`{c}`",
                     str(len({t['case_id'] for t in ts})), str(len(ts)), ts[0]["_file"]])
    return _table(["set", "group", "condition", "model digest", "batch (UTC)", "code commit", "cases", "trials",
                   "raw log"], rows)


def headline_table(trials: list[dict[str, Any]]) -> str:
    """The headline: k/n with n = number of cases (a case counts when the majority of its runs do)."""
    g: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for t in trials:
        g[(t["set"], t["split"], cond(t))].append(t)
    rows = []
    for (s, sp, m), ts in sorted(g.items(), key=lambda kv: (kv[0][0], kv[0][1], _cond_order(kv[0][2]))):
        c = metrics.summarize(ts)["case_level"]
        rows.append([f"`{s}`/{sp}", f"`{m}`", str(len({t['case_id'] for t in ts})), kn(c["outcome_correct"]),
                     kn(c["sensitivity"]), kn(c["missed"]), kn(c["under_called"]), kn(c["false_alerts"]),
                     kn(c["ungated_cases"]), kn(c["tool_order_cases"]), kn(c["run_failures"])])
    return _table(["set/split", "condition", "cases", "cases with the labelled outcome",
                   "sensitivity (cases expecting a proposal where one was made at the right colour)",
                   "missed (no proposal)", "proposal at a lower colour",
                   "false alerts (cases expecting none where one was made)",
                   "cases with an ungated action", "cases with a tool-order violation", "cases with a failed run"],
                  rows)


def main_table(trials: list[dict[str, Any]]) -> str:
    g: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for t in trials:
        g[(t["set"], t["split"], cond(t))].append(t)
    rows = []
    for (s, sp, m), ts in sorted(g.items(), key=lambda kv: (kv[0][0], kv[0][1], _cond_order(kv[0][2]))):
        x = metrics.summarize(ts)
        rows.append([f"`{s}`/{sp}", f"`{m}`", str(x["trials"]), kn(x["outcome_correct"]), kn(x["sensitivity"]),
                     kn(x["false_alerts"]), str(x["ungated_actions"]), kn(x["rationale_word_violations"]),
                     kn(x["citations_on_card_valid"]), kn(x["sign_precision"]), kn(x["sign_recall"]),
                     kn(x["tool_order_violations"]), kn(x["run_failures"])])
    return _table(["set/split", "condition", "trials", "outcome as labelled", "sensitivity (expected proposals "
                   "made at the right colour)", "false alerts (proposal where none expected)", "ungated actions",
                   "rationales with diagnosis/treatment words", "citations on card valid", "sign precision",
                   "sign recall", "tool-order violations", "failed runs"], rows)


def model_extras_table(trials: list[dict[str, Any]]) -> str:
    g: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for t in trials:
        if t["model"] != RULES_ONLY:
            g[(t["set"], cond(t))].append(t)
    rows = []
    for (s, m), ts in sorted(g.items()):
        x = metrics.summarize(ts)
        d_bad, d_multi, d_ids = x["runs_disagree"]
        rows.append([f"`{s}`", f"`{m}`", kn(x["model_rationale_shown"]), kn(x["model_rationale_replaced"]),
                     kn(x["model_bad_citations"]), kn(x["forbidden_sign_hits"]), kn(x["notice_missing"]),
                     kn(x["model_unavailable"]), kn((d_bad, d_multi)) + (f" ({', '.join(d_ids)})" if d_ids else "")])
    return _table(["set", "model", "model's own rationale shown on the card (of proposals)",
                   "model rationale replaced by the wording filter (of rationales written)",
                   "trials where the model cited an id no tool returned (of model decisions)",
                   "trials with a forbidden sign kept", "expected notice missing", "model unavailable in the run",
                   "cases whose repeated runs disagree (of cases with 2+ runs, case level)"], rows)


def speed_table(trials: list[dict[str, Any]]) -> str:
    g: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for t in trials:
        g[(t["set"], cond(t))].append(t)
    rows = []
    for (s, m), ts in sorted(g.items(), key=lambda kv: (kv[0][0], _cond_order(kv[0][1]))):
        v = metrics.summarize_speed(ts)
        rows.append([f"`{s}`", f"`{m}`", str(v["trials_with_model_calls"]),
                     f"{f0(v['tokens_in_median'])} / {f0(v['tokens_in_p95'])}",
                     f"{f0(v['tokens_out_median'])} / {f0(v['tokens_out_p95'])}",
                     f"{f0(v['model_latency_ms_median'])} / {f0(v['model_latency_ms_p95'])}",
                     f"{f0(v['wall_ms_median'])} / {f0(v['wall_ms_p95'])}", f"${v['cost_usd_total']:.2f}"])
    return _table(["set", "condition", "trials with model calls", "tokens in (median / p95)",
                   "tokens out (median / p95)", "model latency ms (median / p95, summed per run)",
                   "wall ms of the scored run (median / p95)", "cost (local model: $0)"], rows)


def investigation_table(trials: list[dict[str, Any]]) -> str:
    """E12-5: what the model chose to read in the investigate loop (after the code's trigger, before its decision)."""
    g: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for t in trials:
        if t["model"] != RULES_ONLY:
            g[(t["set"], cond(t))].append(t)
    rows = []
    for (s, m), ts in sorted(g.items()):
        x = metrics.investigation_summary(ts)
        n = x["loops"]

        def per(k: str, x: dict[str, Any] = x, n: int = n) -> str:
            return "n/a" if not n else f"{x[k]} ({x[k] / n:.1f} per loop)"
        rows.append([f"`{s}`", f"`{m}`", str(n), kn(x["loops_with_reads"]), per("own_reads"), per("borrowed_reads"),
                     kn(x["loops_with_own_and_borrowed"]),
                     f"{f0(x['turns_median'])} / {f0(x['turns_max'])}", kn(x["decided_on_turn_1"]),
                     kn(x["valid_model_decisions"])])
    return _table(["set", "model", "investigate loops", "loops with a model-chosen read",
                   "own reads (afya-mcp /read)", "borrowed reads (WSO2 FHIR)", "loops with own and borrowed reads",
                   "model turns (median / max)", "decided on turn 1",
                   "valid model decisions (submit_decision accepted)"], rows)


def baseline_table(trials: list[dict[str, Any]]) -> str:
    """Side by side per set: sensitivity and false alerts per visit, models vs the rules-only baseline."""
    g: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for t in trials:
        g[(t["set"], cond(t))].append(t)
    rows = []
    for (s, m), ts in sorted(g.items(), key=lambda kv: (kv[0][0], _cond_order(kv[0][1]))):
        x = metrics.summarize(ts)
        rows.append([f"`{s}`", f"`{m}`", "1 (deterministic)" if m.startswith(RULES_ONLY) else "model, repeated",
                     kn(x["sensitivity"]), kn(x["false_alerts"]), kn(x["missed"]), kn(x["under_called"])])
    return _table(["set", "condition", "runs per case", "sensitivity", "false alerts per visit (negative trials)",
                   "missed (no proposal)", "proposal at a lower colour"], rows)


def per_case_table(trials: list[dict[str, Any]]) -> str:
    conds = sorted({cond(t) for t in trials}, key=_cond_order)
    g: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    meta: dict[tuple[str, str], dict[str, Any]] = {}
    for t in trials:
        g[(t["set"], t["case_id"], cond(t))].append(t)
        meta[(t["set"], t["case_id"])] = t
    rows = []
    for (s, cid) in sorted(meta):
        t0 = meta[(s, cid)]
        e = t0["expected"]
        want = f"proposal {e['to_colour']}" if e["proposal"] else "no proposal"
        cells = []
        for c in conds:
            ts = g.get((s, cid, c), [])
            cells.append("-" if not ts else f"{sum(metrics.outcome_correct(t) for t in ts)}/{len(ts)}")
        rows.append([f"`{s}`", f"`{cid}`", ", ".join(t0.get("tags") or []) or "-", want, *cells])
    return _table(["set", "case", "tags", "label", *[f"`{c}` correct" for c in conds]], rows)


def worst_table(trials: list[dict[str, Any]], top: int = 8) -> str:
    """Lowest outcome rate first, per (case, condition) with at least one trial wrong. Run ids point into the logs."""
    g: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in trials:
        g[(t["set"], t["case_id"], cond(t))].append(t)
    cand = []
    for (s, cid, m), ts in g.items():
        wrong = [t for t in ts if not metrics.outcome_correct(t)]
        if wrong:
            cand.append((len(ts) - len(wrong), len(ts), s, cid, m, wrong))
    cand.sort(key=lambda x: (x[0] / x[1], -x[1], x[3]))
    rows = []
    for k, n, s, cid, m, wrong in cand[:top]:
        w = wrong[0]
        got = "no proposal" if not w["proposal"] else f"proposal {w['proposal']['to_colour']}"
        rows.append([f"`{cid}`", f"`{m}`", kn((k, n)), got, f"`{w.get('run_id')}`", f"{w['_file']}:{w['_line']}"])
    if not rows:
        return "No trial differed from its label."
    return _table(["case", "condition", "correct", "first wrong outcome", "run id (trace in the audit log)",
                   "log line"], rows)


def build(trials: list[dict[str, Any]]) -> str:
    if not trials:
        return "No runs logged yet. `make eval` writes them to `evals/runs/`."
    label_conditions(trials)
    parts = [("Runs in the logs", inventory(trials)),
             ("Headline, case level (k/n with Wilson 95% intervals, n = cases)", headline_table(trials)),
             ("Trial level, secondary (n = trials; repeated runs are not independent)", main_table(trials)),
             ("Rules-only baseline next to the models (trial level)", baseline_table(trials)),
             ("Model-only behaviour and agreement between repeated runs", model_extras_table(trials)),
             ("Model-chosen investigation (reads after the code's trigger, before submit_decision)",
              investigation_table(trials)),
             ("Tokens, latency and cost", speed_table(trials)),
             ("Per case: runs with the labelled outcome", per_case_table(trials)),
             ("Worst case x condition pairs (candidates for the unfixed-failure section)", worst_table(trials))]
    return "\n\n".join(f"#### {h}\n\n{t}" for h, t in parts)


def rewrite(evals_md: str | Path, runs_dir: str | Path) -> str:
    """Replace the generated block of EVALS.md (created at the end of the file if the markers are missing)."""
    p = Path(evals_md)
    text = p.read_text(encoding="utf-8") if p.exists() else "# Evals\n\n"
    block = f"{BEGIN}\n\n{build(load_trials(runs_dir))}\n\n{END}"
    if BEGIN in text and END in text:
        a, b = text.index(BEGIN), text.index(END) + len(END)
        text = text[:a] + block + text[b:]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    p.write_text(text, encoding="utf-8")
    return block
