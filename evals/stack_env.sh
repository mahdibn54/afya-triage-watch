#!/bin/sh
# Prints the exports `python -m evals run` needs to reach the compose stack from the host (container IPs change on
# every `docker compose up`, so run this each time):  eval "$(sh evals/stack_env.sh)"
# Needs: the stack running, .env in the repo root (AFYA_APP_PASSWORD, AFYA_MCP_CLIENT_SECRET).
# Nothing is hard-coded: container ids come from `docker compose ps -q <service>`, network names from the compose
# project label of that container (<project>_<network>), the Ollama address from OLLAMA_HOST in .env (default: the
# gateway of Docker's default bridge, 172.17.0.1 on a standard install). 
set -eu
cd "$(dirname "$0")/.."
. ./.env
cid() { id=$(docker compose ps -q "$1"); [ -n "$id" ] || { echo "service $1 is not running" >&2; exit 1; }; echo "$id"; }
project() { docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$1"; }
# ip <service> <compose network name>: address of the service's container on that network
ip() {
  c=$(cid "$1")
  docker inspect -f "{{(index .NetworkSettings.Networks \"$(project "$c")_$2\").IPAddress}}" "$c"
}
PG=$(ip postgres app)
echo "export DATABASE_URL='postgresql://afya_app:${AFYA_APP_PASSWORD}@${PG}:5432/afya'"
# The automated tests (pytest in mcp/ and api/) use this database, never DATABASE_URL (the stack's own data).
echo "export TEST_DATABASE_URL='postgresql://afya_app:${AFYA_APP_PASSWORD}@${PG}:5432/afya_test'"
# E13-3: OAuth. The URLs keep the service names (afya-mcp's resource URIs, the issuer and its TLS name must match);
# EVAL_RESOLVE tells evals/host_gateway.py which container address each name connects to. The local CA certificate
# is copied to .afya/auth-ca.crt (git-ignored) so the host trusts the authorization server's HTTPS.
mkdir -p .afya
docker cp "$(cid api):/auth-ca/ca.crt" .afya/auth-ca.crt >/dev/null
echo "export AFYA_MCP_ACT_URL='https://afya-mcp:9000/act/mcp'"
echo "export AFYA_AUTH_ISSUER='https://auth.afya.internal:9091'"
echo "export AFYA_AUTH_CA_FILE='$(pwd)/.afya/auth-ca.crt'"
echo "export AFYA_MCP_CLIENT_ID='afya-api'"
echo "export AFYA_MCP_CLIENT_SECRET='${AFYA_MCP_CLIENT_SECRET:?set AFYA_MCP_CLIENT_SECRET in .env}'"
# WSO2 is on its own network "borrowed" (with the api only); it never receives an afya credential.
echo "export WSO2_MCP_URL='http://wso2-fhir-mcp:8000/mcp'"
echo "export EVAL_RESOLVE='afya-mcp=$(ip afya-mcp mcp),auth.afya.internal=$(ip auth auth),wso2-fhir-mcp=$(ip wso2-fhir-mcp borrowed)'"
echo "export EVAL_HAPI_URL='http://$(ip hapi fhir_rw):8080/fhir'"
# Optional local model (MODEL_PROVIDER=ollama only): OLLAMA_HOST from .env, else the default bridge's gateway.
oh="${OLLAMA_HOST:-$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)}"
oh="${oh:-172.17.0.1}"
case "$oh" in *:*) ;; *) oh="$oh:11434" ;; esac
echo "export OLLAMA_BASE_URL='http://$oh'"
