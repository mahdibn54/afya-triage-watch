# Qwen Groq evaluation handoff for Mahdi

Dheker asks: if you can, please continue the remaining runs. The synthetic batch stopped at Groq's daily limit. As of 10 November 2026, 69 of 250 model trials and all 50 rules-only baseline trials are saved. Of the 69, 65 matched the author-written expected proposal and colour. These are preliminary synthetic results, not clinical validation. The runner reported one model-unavailable trial; preserve it for review. The 11 earlier network-blocked attempts were excluded, not counted.

Batch: `20261109T162312Z`; model: `groq:qwen/qwen3.8-27b`; 50 cases, five runs each. The exact combined case file is `all50.json` in this directory. Its SHA-256 is `8a7568b9644e05e19d051979b42098f9a325f32e9ce8fb48a5b941a92de81cc4`. Source commit: `d5e1526e9bf761f324faa2371a6f58970d97f3f8` (see `manifest.json` for environment versions). Avoid changing model instructions, code, cases or run settings mid-batch; document any unavoidable environment differences. The original runner used a separate Docker stack and the Python/package versions in the manifest. Its local Docker volumes and credentials are not shared in Git.

To continue using the existing harness, start an isolated synthetic stack from that source revision, set up its OAuth and service connections as described in `evals/README.md` and `evals/stack/README.md`, and use your own Groq key in your local environment. Put the two committed batch JSONL files in that checkout's `evals/runs/`, and use this exact case file and batch ID. From the repository root, after configuring the stack environment:

```sh
DEMO_MODE=1 DATA_CLASSIFICATION=synthetic python -m evals run --cases evals/batches/20261109/all50.json --models groq:qwen/qwen3.8-27b --runs 5 --rules-only-runs 1 --resume 20261109T162312Z
```

The `all50` filename is significant: the runner derives the output filename from it and skips trial IDs already present in that file. Verify it reports 69 already written and 181 to run before continuing. It saves each completed trial and stops at the provider limit; resume with the same command and batch ID when quota is available. Do not run the batch on two machines at once or overwrite another person's new results. Share the updated JSONL files after the run and never commit keys or credentials.
