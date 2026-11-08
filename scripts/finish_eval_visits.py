#!/usr/bin/env python3
"""One-off: finish the in-progress Encounters of EV- synthetic eval patients so they leave the waiting room.

Dry run by default (prints counts only). `--apply` sets status `finished` on those Encounters (no delete). Only
Patients labelled EV-<case>-<6 hex> are selected (see evals/eval_visits.py): never P-014 or a seeded demo patient.
Needs EVAL_HAPI_URL: eval "$(sh evals/stack_env.sh)"."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # run from anywhere: `evals` lives at the repo root
from evals.eval_visits import find_waiting_eval_encounters, finish_encounter


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="really finish them (default: dry run, counts only)")
    a = ap.parse_args(argv)
    hapi = os.environ.get("EVAL_HAPI_URL")
    if not hapi:
        print('EVAL_HAPI_URL is not set; run: eval "$(sh evals/stack_env.sh)"', file=sys.stderr)
        return 2
    with httpx.Client(timeout=30) as client:
        found = find_waiting_eval_encounters(client, hapi)
        print(f"waiting eval encounters (EV- patients): {len(found)}")
        if not a.apply:
            print("dry run: nothing changed (use --apply to finish them)")
            return 0
        for enc in found:
            finish_encounter(client, hapi, enc)
    print(f"finished: {len(found)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
