"""Safe probes of actual Afya tools and a visible SDK error, against the offline conformance wrapper."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

CATALOGUES = {"read": {"compute_tews", "check_deterioration", "get_queue_state"},
              "act": {"record_vitals", "raise_recheck_flag", "notify_staff", "seed_demo_visit"},
              "ui": {"visit_timeline", "queue_state", "demo_visit"}}
META = "io.modelcontextprotocol/"


def arguments_rejected(answer: dict, required: list[str]) -> bool:
    if answer.get("error", {}).get("code") == -32602:
        return True
    result = answer.get("result", {})
    text = " ".join(c.get("text", "") for c in result.get("content", []))
    return (result.get("isError") is True and "validation error" in text.lower()
            and "Field required" in text and any(name in text for name in required))


def run(base: str) -> list[dict]:
    rows = []
    with httpx.Client(timeout=20) as client:
        for mount, expected in CATALOGUES.items():
            def rpc(method, params, mount=mount):
                params = {**params, "_meta": {META + "protocolVersion": "2026-07-28",
                                             META + "clientInfo": {"name": "afya-application-probe", "version": "1"},
                                             META + "clientCapabilities": {}}}
                headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28",
                           "Mcp-Method": method}
                if "name" in params:
                    headers["Mcp-Name"] = params["name"]
                response = client.post(f"{base}/{mount}/mcp", headers=headers,
                                       json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                if response.headers.get("content-type", "").startswith("text/event-stream"):
                    return next(json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:"))
                return response.json()

            try:
                tools = rpc("tools/list", {})["result"]["tools"]
                names = {t["name"] for t in tools}
                rows.append({"mount": mount, "name": "catalogue", "status": "PASS" if names == expected else "FAIL",
                             "detail": f"Actual tool names: {', '.join(sorted(names))}"})
                tool = next(t for t in tools if t["inputSchema"].get("required"))
                answer = rpc("tools/call", {"name": tool["name"], "arguments": {}})
                rejected = arguments_rejected(answer, tool["inputSchema"]["required"])
                rows.append({"mount": mount, "name": "invalid-tool-arguments", "status": "PASS" if rejected else "FAIL",
                             "detail": f"Missing required inputs to {tool['name']} rejected; no clinical data supplied."})
                answer = rpc("tools/call", {"name": "afya_nonexistent_tool", "arguments": {}})
                code = answer.get("error", {}).get("code")
                rows.append({"mount": mount, "name": "unknown-tool-error", "actual_code": code,
                             "status": "PASS" if code == -32602 else "FAIL",
                             "detail": f"Expected -32602 Invalid params, got {code}."})
                answer = rpc("prompts/get", {"name": "afya_nonexistent_prompt"})
                code = answer.get("error", {}).get("code")
                rows.append({"mount": mount, "name": "unknown-prompt-error", "actual_code": code,
                             "status": "PASS" if code == -32602 else "FAIL",
                             "detail": f"Expected -32602 Invalid params, got {code}."})
            except (httpx.HTTPError, KeyError, ValueError, StopIteration) as error:
                rows.append({"mount": mount, "name": "probe-error", "status": "ERROR",
                             "detail": f"{type(error).__name__}: {error}"})
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--url", default="http://localhost:9100")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(run(args.url), indent=2), encoding="utf-8")
