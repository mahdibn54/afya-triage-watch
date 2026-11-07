# Eval harness (E8). Full instructions: evals/README.md
PY      ?= python3
CASES   ?= evals/cases/m_fixtures
MODELS  ?= qwen3:8b,qwen3:4b-instruct
RUNS    ?= 5
RUNS_DIR ?= evals/runs
RULES_ONLY_RUNS ?= 1
# after a provider limit: RESUME=<batch> appends to that batch and skips the trials already written
RESUME  ?=
TOKEN_BUDGET ?= 0

.PHONY: eval eval-tables eval-test

# Live: groups B (each model, RUNS runs per case) and C (rules-only, once per case) on the cases at CASES, raw JSONL to
# evals/runs/, then the tables in EVALS.md. Needs the stack and Ollama; first: eval "$(sh evals/stack_env.sh)"
eval:
	DEMO_MODE=1 $(PY) -m evals run --cases $(CASES) --models "$(MODELS)" --runs $(RUNS) --out $(RUNS_DIR) \
		--rules-only-runs $(RULES_ONLY_RUNS) --token-budget $(TOKEN_BUDGET) $(if $(RESUME),--resume $(RESUME))
	$(PY) -m evals tables --runs $(RUNS_DIR)

# Offline: rebuild the generated tables in EVALS.md from the logs in evals/runs/ (no stack, no model).
eval-tables:
	$(PY) -m evals tables --runs $(RUNS_DIR)

# Unit tests of the statistics and metrics.
eval-test:
	$(PY) -m pytest evals/tests -q
