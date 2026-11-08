"""Application-scoped interpretation of raw official results; never a certification score."""
from __future__ import annotations

import argparse
import html
import json
import os
from collections import Counter
from pathlib import Path

import yaml

try:
    from scripts.conformance_report import scenarios, verdict
except ModuleNotFoundError:
    from conformance_report import scenarios, verdict

SCOPES = {"applicable", "fixture_dependent", "not_offered", "not_exercised"}
STATUSES = {"SUCCESS", "FAILURE", "WARNING", "SKIPPED", "INFO"}


def assess_run(data: dict, profile: dict) -> dict:
    errors, rows = [], []
    for name in sorted(set(data) ^ set(profile)):
        errors.append(f"Scenario coverage drift: {name} {'missing' if name not in data else 'unclassified'}")
    for name, policy in profile.items():
        if name not in data:
            continue
        checks = data[name]
        scope = policy.get("scope")
        excluded = policy.get("excluded_checks", {})
        if scope not in SCOPES or not policy.get("reason"):
            errors.append(f"{name}: invalid scope policy")
        ids = [c["id"] for c in checks]
        if any(c["status"] not in STATUSES for c in checks) or not checks:
            errors.append(f"{name}: empty or invalid checks")
        for check in checks:
            if check["id"].startswith("wire-schema") and check["status"] == "FAILURE":
                errors.append(f"{name}:{check['id']}: {check.get('errorMessage', 'wire validation failed')}")
        for check_id in set(excluded) - set(ids):
            errors.append(f"{name}: excluded check {check_id} missing; review scope")
        selected = [c for c in checks if c["id"] not in excluded]
        if scope == "applicable":
            failures = [c for c in selected if c["status"] == "FAILURE"]
            meaningful = [c for c in selected if c["status"] in {"SUCCESS", "WARNING"}
                          and not c["id"].startswith("wire-schema")]
            status = "FAIL" if failures else "WARN" if any(c["status"] == "WARNING" for c in selected) else "PASS"
            if failures:
                errors.extend(f"{name}:{c['id']}: {c.get('errorMessage', 'failed')}" for c in failures)
            if not meaningful:
                status = "NOT_ASSESSED"
                errors.append(f"{name}: no executed application assertions")
        else:
            status = "NOT_ASSESSED"
        rows.append({"scenario": name, "raw": verdict(checks), "scope": scope, "application": status,
                     "reason": policy["reason"], "assessment": policy.get("assessment", "unreviewed"),
                     "specification": policy.get("specification", []), "excluded_checks": excluded,
                     "check_counts": dict(Counter(c["status"] for c in checks))})
    return {"counts": dict(Counter(r["application"] for r in rows)),
            "raw_counts": dict(Counter(verdict(c) for c in data.values())), "rows": rows, "errors": errors}


def assess_probes(probes: list[dict], known: dict) -> dict:
    expected = {(m, n) for m in ("read", "act", "ui")
                for n in ("catalogue", "invalid-tool-arguments", "unknown-prompt-error", "unknown-tool-error")}
    found = [(p["mount"], p["name"]) for p in probes]
    errors, rows = [], []
    if set(found) != expected or len(found) != len(expected):
        errors.append("Supplemental probe coverage incomplete or duplicated")
    for probe in probes:
        row = dict(probe)
        baseline = known.get(probe["name"])
        if baseline:
            if probe["status"] == "FAIL" and probe.get("actual_code") == baseline["actual_code"]:
                row["status"] = "KNOWN_FAILURE"
                row["reason"] = baseline["reason"]
            else:
                errors.append(f"{probe['mount']}/{probe['name']}: baseline changed; review result")
        elif probe["status"] != "PASS":
            errors.append(f"{probe['mount']}/{probe['name']}: {probe.get('detail', 'failed')}")
        rows.append(row)
    return {"rows": rows, "counts": dict(Counter(r["status"] for r in rows)), "errors": errors}


def render(report: dict) -> str:
    lines = ["# Afya MCP application regression report", "",
             "**This is not a full official conformance pass, SDK tier result or certification.**", "",
             f"Tool: `{report['tool']}`. Protocol: `{report['protocol']}`. Commit: `{report['commit']}`.", "",
             ("The official frozen requirement set ran unchanged, without expected-failure waivers. "
             "Raw FAIL results remain FAIL. The application profile below is our own scope decision, "
              "not an official exemption."),
             "", "| Run | Raw PASS / WARN / FAIL | Application PASS / WARN / FAIL | Not assessed |",
             "|---|---|---|---|"]
    for name, result in report["runs"].items():
        raw, app = result["raw_counts"], result["counts"]
        lines.append(f"| {name} | {' / '.join(str(raw.get(k, 0)) for k in ('PASS', 'WARN', 'FAIL'))} | "
                     f"{' / '.join(str(app.get(k, 0)) for k in ('PASS', 'WARN', 'FAIL'))} | "
                     f"{app.get('NOT_ASSESSED', 0)} |")
    lines += ["", ("Application PASS applies only to the selected assertions. `server-stateless` excludes four "
              "fixture-dependent checks, listed below. Skipped checks are not passes. Wire-schema failures are gated "
              "even in scenarios outside the application scope."), "", "## Supplemental application probes", "",
              "These are Afya checks, not official framework scenarios.", "",
              "| Mount | Probe | Result | Detail |", "|---|---|---|---|"]
    for p in report["probes"]["rows"]:
        lines.append(f"| {p['mount']} | {p['name']} | {p['status']} | {p.get('reason', p.get('detail', ''))} |")
    for name, result in report["runs"].items():
        lines += ["", f"## {name}: scope and raw outcomes", "",
                  "| Scenario | Raw | Application | Scope / reason |", "|---|---|---|---|"]
        for row in result["rows"]:
            note = row["assessment"] + ": " + row["reason"]
            note += " ".join(f" Excluded {k}: {v}" for k, v in row["excluded_checks"].items())
            note += " " + " ".join(f"[Spec]({url})" for url in row["specification"])
            lines.append(f"| {row['scenario']} | {row['raw']} | {row['application']} | {row['scope']}: {note} |")
    lines += ["", "## Gate result", "", "FAILED" if report["errors"] else
              ("REGRESSION BASELINE ACCEPTED. Known failures remain; this is not full conformance."
               if report["probes"]["counts"].get("KNOWN_FAILURE") else
               "APPLICATION CHECKS PASSED. No failures waived; this is not full official conformance.")]
    lines += [f"- {e}" for e in report["errors"]]
    lines += ["", "## Coverage limits", "",
              ("- Browser OAuth, alternative service-auth flows and interactive inputs are not assessed by this driver; "
              "no security compliance claim follows from excluding them."),
              ("- Protocol scenarios use an offline issuer with injected tokens. Resource-server protection is tested "
              "separately by mcp/tests/test_auth.py and scripts/smoke.sh."),
              "- Empty prompt/resource lists are permitted. Identifier errors are covered by the supplemental probes.",
              "- Clinical scoring, safety and real patient-data handling are outside protocol conformance."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=Path("docs/conformance/application-profile.yaml"))
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA", "local working tree"))
    args = parser.parse_args()
    profile = yaml.safe_load(args.profile.read_text(encoding="utf-8"))
    report = {"tool": profile["tool"], "protocol": profile["protocol"], "commit": args.commit, "runs": {}, "errors": []}
    for name in ("server-read", "server-act", "server-ui", "client"):
        leg = "server" if name.startswith("server-") else "client"
        try:
            result = assess_run(scenarios(args.root / name), profile[leg])
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            result = {"counts": {}, "raw_counts": {}, "rows": [], "errors": [str(e)]}
        report["runs"][name] = result
        report["errors"].extend(f"{name}: {e}" for e in result["errors"])
    try:
        report["probes"] = assess_probes(json.loads((args.root / "probes.json").read_text()),
                                         profile["known_probe_failures"])
    except (OSError, ValueError, KeyError) as e:
        report["probes"] = {"rows": [], "counts": {}, "errors": [f"Missing/invalid supplemental probes: {e}"]}
    report["errors"].extend(report["probes"]["errors"])
    args.root.mkdir(parents=True, exist_ok=True)
    text = render(report)
    (args.root / "application-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.root / "application-report.md").write_text(text, encoding="utf-8")
    summary_rows = []
    for name, result in report["runs"].items():
        raw, app = result["raw_counts"], result["counts"]
        cells = [name, " / ".join(str(raw.get(k, 0)) for k in ("PASS", "WARN", "FAIL")),
                 " / ".join(str(app.get(k, 0)) for k in ("PASS", "WARN", "FAIL")),
                 str(app.get("NOT_ASSESSED", 0))]
        summary_rows.append("<tr>" + "".join("<td>" + html.escape(c) + "</td>" for c in cells) + "</tr>")
    known_count = report["probes"]["counts"].get("KNOWN_FAILURE", 0)
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Afya MCP application regression report</title><style>'
            'body{max-width:1000px;margin:24px auto;padding:0 16px;color:#182126;background:#fafafa;'
            'font:16px/1.5 system-ui,sans-serif}h1{font-size:28px;line-height:1.2}h2{font-size:21px}'
            '.notice{padding:16px;border:1px solid #956700;background:#fff3cc;border-radius:8px}'
            '.table{overflow:auto}table{border-collapse:collapse;min-width:0;width:100%}'
            'th,td{text-align:left;padding:8px;font-size:14px;border-bottom:1px solid #ccd1d4}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace}'
            'summary{cursor:pointer;padding:12px 0}</style></head><body><main>'
            '<h1>Afya MCP application regression report</h1>'
            '<p class="notice"><strong>Not a full conformance pass or certification.</strong> '
            'These are scoped application checks. Raw official failures remain visible.</p>'
            '<p>Accepted protocol failures: <strong>' + str(known_count) + '</strong> probes across the three mounts. ' +
            ('Known-error baselines remain; see the complete report.</p>' if known_count else
             'No known protocol failures are accepted by the application gate.</p>') +
            '<h2>Results</h2><p>Counts are PASS / WARN / FAIL. Not assessed never means passed.</p>'
            '<div class="table"><table><thead><tr><th>Run</th><th>Raw official</th><th>Application</th>'
            '<th>Not assessed</th></tr></thead><tbody>' + "".join(summary_rows) + '</tbody></table></div>'
            '<p>Server application counts exclude four fixture-dependent stateless checks. '
            'The complete scope decisions and known failures are below.</p>'
            '<details><summary>Complete report and scope decisions</summary><pre>' + html.escape(text) +
            '</pre></details></main></body></html>')
    (args.root / "application-report.html").write_text(page, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
            out.write(text)
    print(text.split("## Supplemental application probes")[0])
    if report["probes"]["counts"].get("KNOWN_FAILURE"):
        print("::warning::Known failures remain. See application-report.md; no full conformance claim.")
    for error in report["errors"]:
        print(error)
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
