"""python -m evals run|tables  (see evals/README.md)."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from . import report
from .cases import load_cases

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run groups B (models) and C (rules-only) live and write JSONL to --out")
    r.add_argument("--cases", required=True, help="a case file or a directory of case files")
    r.add_argument("--models", default="qwen3:8b,qwen3:4b-instruct",
                   help="comma-separated: Ollama tags, OpenRouter ids (with a slash) or ollama_cloud:<name>")
    r.add_argument("--runs", type=int, default=5, help="runs per case per model (group B)")
    r.add_argument("--rules-only-runs", type=int, default=1, help="runs per case for group C (0 = skip)")
    r.add_argument("--out", default=str(ROOT / "evals" / "runs"))
    r.add_argument("--only", default="", help="comma-separated case ids (smoke runs; leave empty for the real run)")
    r.add_argument("--no-cleanup", action="store_true", help="leave pending proposals of eval visits in the queue")
    t = sub.add_parser("tables", help="rebuild the tables in EVALS.md from the logs (no stack needed)")
    t.add_argument("--runs", default=str(ROOT / "evals" / "runs"))
    t.add_argument("--evals-md", default=str(ROOT / "EVALS.md"))
    a = ap.parse_args(argv)
    if a.cmd == "tables":
        report.rewrite(a.evals_md, a.runs)
        print(f"{a.evals_md}: tables rebuilt from {a.runs}")
        return 0
    from .runner import run_all  # imports the api package and needs the stack: only for `run`
    cases = load_cases(a.cases)
    if a.only:
        want = set(a.only.split(","))
        cases = [c for c in cases if c.id in want]
    models = [m for m in a.models.split(",") if m]
    set_name = Path(a.cases).stem if Path(a.cases).is_file() else Path(a.cases).name
    for k in ("DATABASE_URL", "AFYA_MCP_ACT_URL", "WSO2_MCP_URL", "EVAL_HAPI_URL"):
        if k not in os.environ:
            print(f"{k} is not set; run: eval \"$(sh evals/stack_env.sh)\"", file=sys.stderr)
            return 2
    paths = asyncio.run(run_all(cases, models, a.runs, a.rules_only_runs, Path(a.out), set_name,
                                os.environ.get("OLLAMA_BASE_URL", "http://172.17.0.1:11434"), not a.no_cleanup))
    for p in paths:
        print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
