#!/usr/bin/env bash
# Smoke test of the running stack (docker compose up --build -d). Exit code is non-zero if any check fails.
# Everything runs through `docker compose exec`: no service publishes a host port, so there is nothing to curl.
set -u
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

FAILS=0
ok()   { echo "PASS  $1"; }
bad()  { echo "FAIL  $1"; FAILS=$((FAILS + 1)); }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi; }
refuse() { local name=$1; shift; if "$@" >/dev/null 2>&1; then bad "$name"; else ok "$name"; fi; }

dc()  { docker compose "$@"; }
app_psql() { dc exec -T -e PGPASSWORD="$AFYA_APP_PASSWORD" postgres psql -h 127.0.0.1 -U afya_app -d afya -v ON_ERROR_STOP=1 -c "$1"; }
mcpx() { dc exec -T afya-mcp python - "$@"; }

echo "== containers"
for s in postgres hapi gateway wso2-fhir-mcp afya-mcp api; do
  check "$s running" test "$(dc ps --status running --format '{{.Service}}' | grep -cx "$s")" = 1
done
for s in db-init lg-init hapi-perms; do
  check "$s exited 0" test "$(docker inspect -f '{{.State.ExitCode}}' "$(dc ps -a -q "$s")")" = 0
done

echo "== waiting for HAPI (cold start can take a minute or two)"
check "HAPI answers through the gateway" bash -c 'for i in $(seq 60); do docker compose exec -T afya-mcp python -c "import urllib.request as u;u.urlopen(\"http://gateway/fhir/metadata\",timeout=5)" 2>/dev/null && exit 0; sleep 5; done; exit 1'

echo "== database"
check "lg checkpoint tables exist" test "$(dc exec -T postgres psql -U "$PG_SUPERUSER" -d afya -Atc "select count(*) from information_schema.tables where table_schema='lg' and table_name in ('checkpoints','checkpoint_blobs','checkpoint_writes','checkpoint_migrations')" | tr -d '\r')" = 4
check "afya_app INSERT audit_log" app_psql "INSERT INTO afya.audit_log (kind, actor, payload) VALUES ('smoke', 'nurse-a', '{}')"
refuse "afya_app UPDATE audit_log refused" app_psql "UPDATE afya.audit_log SET kind='x'"
refuse "afya_app DELETE audit_log refused" app_psql "DELETE FROM afya.audit_log"
refuse "afya_app TRUNCATE audit_log refused" app_psql "TRUNCATE afya.audit_log"
check "afya_app search_path is afya, lg" test "$(dc exec -T -e PGPASSWORD="$AFYA_APP_PASSWORD" postgres psql -h 127.0.0.1 -U afya_app -d afya -Atc 'show search_path' | tr -d '\r')" = "afya, lg"
refuse "afya_app cannot CREATE TABLE" app_psql "CREATE TABLE afya.x (a int)"

echo "== gateway (read-only front of HAPI)"
gw() { mcpx "$@" <<'PY'
import http.client, sys
method, path = sys.argv[1], sys.argv[2]
c = http.client.HTTPConnection("gateway", 80, timeout=20)
c.putrequest(method, path, skip_accept_encoding=True)   # raw path: no client-side normalisation
c.putheader("Content-Length", "2"); c.putheader("Content-Type", "application/fhir+json"); c.endheaders(b"{}")
print(c.getresponse().status)
PY
}
status_is() { [ "$(gw "$2" "$3" | tr -d '\r\n')" = "$1" ]; }
check "GET /fhir/metadata -> 200" status_is 200 GET /fhir/metadata
for m in POST PUT DELETE PATCH; do check "$m -> 403" status_is 403 "$m" /fhir/Patient; done
check "';' refused"   status_is 403 GET "/fhir/Patient;jsessionid=1"
check "'..' refused"  status_is 403 GET "/fhir/Patient/../metadata"
check "'%2e' refused" status_is 403 GET "/fhir/Patient/%2e%2e/metadata"
check "'\$' refused"  status_is 403 GET "/fhir/Patient/\$everything"
check "subject=Patient%2F1 query works" status_is 200 GET "/fhir/Observation?subject=Patient%2F1"

echo "== network isolation"
check "wso2-fhir-mcp cannot resolve hapi" dc exec -T wso2-fhir-mcp python -c "
import socket,sys
try: socket.gethostbyname('hapi')
except socket.gaierror: sys.exit(0)
sys.exit(1)"
check "wso2-fhir-mcp reaches gateway" dc exec -T wso2-fhir-mcp python -c "import urllib.request as u;u.urlopen('http://gateway/fhir/metadata',timeout=10)"
check "WSO2 MCP initialize at /mcp" dc exec -T api python -c "
import httpx,sys,os
r=httpx.post(os.environ['WSO2_MCP_URL'],headers={'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'smoke','version':'1'}}})
sys.exit(0 if r.status_code==200 and 'serverInfo' in r.text else 1)"

echo "== HAPI persistence"
mcpx <<'PY' >/dev/null 2>&1 && ok "seed marker Patient in HAPI" || bad "seed marker Patient in HAPI"
import httpx
r = httpx.post("http://hapi:8080/fhir/Patient", headers={"Content-Type": "application/fhir+json"}, timeout=30,
               json={"resourceType": "Patient", "identifier": [{"system": "urn:afya:smoke", "value": "persist"}]})
r.raise_for_status()
PY
dc restart hapi >/dev/null 2>&1
check "HAPI back after restart" bash -c 'for i in $(seq 60); do docker compose exec -T afya-mcp python -c "import urllib.request as u;u.urlopen(\"http://hapi:8080/fhir/metadata\",timeout=5)" 2>/dev/null && exit 0; sleep 5; done; exit 1'
check "marker Patient survived restart" mcpx <<'PY'
import httpx, sys
b = httpx.get("http://hapi:8080/fhir/Patient", params={"identifier": "urn:afya:smoke|persist"}, timeout=30).json()
sys.exit(0 if b.get("total", len(b.get("entry", []))) >= 1 else 1)
PY

echo "== afya-mcp against real HAPI"
check "afya-mcp /healthz" dc exec -T afya-mcp python -c "import urllib.request as u;assert u.urlopen('http://127.0.0.1:9000/healthz',timeout=5).read().strip()==b'ok'"
check "api /healthz" dc exec -T api python -c "import urllib.request as u;assert u.urlopen('http://127.0.0.1:8080/healthz',timeout=5).status==200"
check "compute_tews on seeded Patient+Encounter+Observation" mcpx <<'PY'
import asyncio, sys, uuid, httpx
from datetime import date, timedelta
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from afya_mcp.fhir import vitals_observation

H = {"Content-Type": "application/fhir+json"}
F = "http://hapi:8080/fhir"
def post(res):
    r = httpx.post(f"{F}/{res['resourceType']}", json=res, headers=H, timeout=30); r.raise_for_status(); return r.json()["id"]

born = (date.today() - timedelta(days=365 * 40)).isoformat()
pid = post({"resourceType": "Patient", "birthDate": born, "gender": "other"})
eid = post({"resourceType": "Encounter", "status": "in-progress", "class": {"code": "EMER"}, "subject": {"reference": f"Patient/{pid}"}})
obs = vitals_observation(pid, eid, {"resp_rate": 26, "heart_rate": 118, "systolic_bp": 95, "temperature": 38.6,
                                     "spo2": 93, "mobility": "walking", "consciousness": "alert", "trauma": "no"},
                         "smoke-" + uuid.uuid4().hex)
oid = post(obs)

async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/read/mcp/") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("compute_tews", {"observation_id": f"Observation/{oid}"})
            print(res.structuredContent or res.content)
            return not res.isError and "scored" in str(res.structuredContent or res.content)
sys.exit(0 if asyncio.run(main()) else 1)
PY

echo "== host exposure"
PUB=$(docker ps --filter "label=com.docker.compose.project=afya" --format '{{.Names}} {{.Ports}}' | grep -E '0\.0\.0\.0|\[::\]|127\.0\.0\.1' || true)
if [ -z "$PUB" ]; then ok "no service publishes a host port (web profile off)"; else bad "published ports: $PUB"; fi
check "compose publishes only 127.0.0.1:3000" test "$(dc --profile web config | grep -cE 'published:')" -le 1

echo
if [ "$FAILS" -eq 0 ]; then echo "SMOKE OK"; else echo "SMOKE FAILED: $FAILS check(s)"; exit 1; fi
