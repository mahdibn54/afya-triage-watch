#!/bin/sh
# Prints the exports `python -m evals run` needs to reach the compose stack from the host (container IPs change on
# every `docker compose up`, so run this each time):  eval "$(sh evals/stack_env.sh)"
# Needs: the stack running, .env in the repo root (AFYA_APP_PASSWORD), Ollama on 172.17.0.1:11434.
set -eu
cd "$(dirname "$0")/.."
. ./.env
ip() { docker inspect -f "{{(index .NetworkSettings.Networks \"$2\").IPAddress}}" "$1"; }
echo "export DATABASE_URL='postgresql://afya_app:${AFYA_APP_PASSWORD}@$(ip afya-postgres-1 afya_app):5432/afya'"
# The automated tests (pytest in mcp/ and api/) use this database, never DATABASE_URL (the stack's own data).
echo "export TEST_DATABASE_URL='postgresql://afya_app:${AFYA_APP_PASSWORD}@$(ip afya-postgres-1 afya_app):5432/afya_test'"
echo "export AFYA_MCP_ACT_URL='http://$(ip afya-afya-mcp-1 afya_mcp):9000/act/mcp'"
echo "export WSO2_MCP_URL='http://$(ip afya-wso2-fhir-mcp-1 afya_mcp):8000/mcp'"
echo "export EVAL_HAPI_URL='http://$(ip afya-hapi-1 afya_fhir_rw):8080/fhir'"
echo "export OLLAMA_BASE_URL='http://172.17.0.1:11434'"
