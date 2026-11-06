"""Probe for the unfixed failure in EVALS.md (m17-chest-pain): why does map_signs call chest pain 'other'?

Calls the product's own map_signs prompt and schema directly on Ollama (host-side, no stack needed) with small
variants of the complaint and one prompt ablation, 5 seeds each, and writes every raw answer to
evals/probes/m17_probe.jsonl. Run: python evals/probes/probe_m17.py  (OLLAMA_BASE_URL, default 172.17.0.1:11434)
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path

from afya_api import signs as sg
from afya_api.model import ModelSettings, OllamaBackend
from afya_mcp import rules

MODEL = os.environ.get("PROBE_MODEL", "qwen3:8b")
VARIANTS = {
    "original": "Crushing chest pain that started an hour ago.",
    "no_time": "Crushing chest pain.",
    "plain": "I have chest pain.",
    "time_only": "Chest pain that started an hour ago.",
    "now": "I have chest pain right now.",
}
ABLATE = "          \"je n'ai pas de douleur thoracique\" -> CHEST_PAIN, \"douleur thoracique\", other\n"


async def main() -> None:
    chart = next(c for c in rules.load_registry() if c["chart_id"] == "sats_adult_2012")
    codes = json.dumps({c: s["gloss"] for c, s in chart["signs"].items()}, ensure_ascii=False)
    base = ModelSettings(base_url=os.environ.get("OLLAMA_BASE_URL", "http://172.17.0.1:11434"), model=MODEL)
    out = Path(__file__).with_name("m17_probe.jsonl")
    with out.open("w", encoding="utf-8") as f:
        for prompt_name, prompt in (("product_prompt", sg.PROMPT), ("without_french_negation_example",
                                                                    sg.PROMPT.replace(ABLATE, ""))):
            assert prompt_name == "product_prompt" or prompt != sg.PROMPT
            for vname, text in VARIANTS.items():
                for seed in range(1, 6):
                    s = replace(base, seed=seed)
                    backend = OllamaBackend(s)
                    msgs = [{"role": "system", "content": prompt.format(codes=codes)},
                            {"role": "user", "content": f"<complaint>{text}</complaint>"}]
                    r = await backend.chat(msgs, options=s.options("map_signs"), tools=None, format=sg.schema(chart))
                    try:
                        ans = json.loads(r.content)
                    except ValueError:
                        ans = {"unparsed": r.content[:200]}
                    row = {"model": MODEL, "prompt": prompt_name, "variant": vname, "text": text, "seed": seed,
                           "answer": ans}
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    print(prompt_name, vname, seed, json.dumps(ans.get("signs", ans), ensure_ascii=False)[:120])


if __name__ == "__main__":
    asyncio.run(main())
