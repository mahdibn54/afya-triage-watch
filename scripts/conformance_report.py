"""Turn the output directory of `conformance server -o <dir>` into a dated-free markdown table (E13-4).

Usage: python scripts/conformance_report.py <output-dir> [<output-dir> ...]   (server or client runs)
Only scenario names, statuses and the tool's error text are kept; run timestamps in the directory names are dropped.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def scenarios(out: Path) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for checks in sorted(out.rglob("checks.json")):   # client runs nest the auth scenarios under auth/
        d = checks.parent
        name = re.sub(r"^server-|-\d{4}-\d\d-\d\dT.*$", "", d.name)
        key = f"{d.parent.name}/{name}" if d.parent != out else name
        if key in result:
            raise ValueError(f"Duplicate scenario output: {key}; use a fresh result directory")
        result[key] = json.loads(checks.read_text(encoding="utf-8"))
    return result


def verdict(checks: list[dict]) -> str:
    states = {c["status"] for c in checks}
    if "FAILURE" in states:
        return "FAIL"
    return "WARN" if "WARNING" in states else "PASS"


def main(dirs: list[str]) -> None:
    for d in dirs:
        data = scenarios(Path(d))
        counts = {v: sum(verdict(c) == v for c in data.values()) for v in ("PASS", "WARN", "FAIL")}
        print(f"\n### {Path(d).name}: {counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail "
              f"of {len(data)} scenarios\n\n| Scenario | Result | Detail |\n|---|---|---|")
        for name, checks in data.items():
            bad = [c for c in checks if c["status"] in ("FAILURE", "WARNING")]
            detail = "; ".join(f"{c['id']}: {(c.get('errorMessage') or c['status'])[:110]}" for c in bad[:2])
            print(f"| {name} | {verdict(checks)} | {detail.replace('|', '/')} |")


if __name__ == "__main__":
    main(sys.argv[1:])
