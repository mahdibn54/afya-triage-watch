#!/bin/sh
# One command from a fresh clone to the nurse UI with the synthetic waiting room:  make demo  (or sh scripts/demo.sh)
# 1. creates .env from .env.example with a new random value for every CHANGE_ME (an existing .env is kept as it is);
# 2. builds and starts the whole stack in the background; 3. loads the 20 synthetic patients (safe to rerun).
# No model key is needed: without one the agent proposes from the fixed SATS rules with a "no model" notice.
# Add GROQ_API_KEY (with MODEL_PROVIDER=groq) or OLLAMA_API_KEY to .env and rerun to use the open-weights model.
set -eu
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  command -v openssl >/dev/null || { echo "openssl is needed to generate the secrets" >&2; exit 1; }
  umask 077
  while IFS= read -r line; do
    case "$line" in
      \#*|"") printf '%s\n' "$line" ;;
      *=CHANGE_ME*) printf '%s=%s\n' "${line%%=*}" "$(openssl rand -hex 24)" ;;
      *) printf '%s\n' "$line" ;;
    esac
  done < .env.example > .env
  echo "Created .env with fresh random secrets (git-ignored; never commit it)."
else
  echo "Using the existing .env."
fi
if grep -q '=CHANGE_ME' .env; then
  echo ".env still has CHANGE_ME values: set them, or delete .env and rerun to generate them." >&2
  exit 1
fi

docker compose --profile web up -d --build
docker compose --profile seed run --build --rm seed

echo
echo "Afya Triage Watch is running: http://127.0.0.1:${WEB_PORT:-3000}"
echo "Stop it with: docker compose --profile web down   (data is kept in Docker volumes)"
