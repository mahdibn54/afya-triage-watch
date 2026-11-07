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
app_atc() { dc exec -T -e PGPASSWORD="$AFYA_APP_PASSWORD" postgres psql -h 127.0.0.1 -U afya_app -d afya -Atc "$1" | tr -d '\r'; }
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
check "afya_app INSERT audit_log" app_psql "INSERT INTO afya.audit_log (kind, actor, auth, payload) VALUES ('smoke', 'nurse-a', 'demo_switcher', '{}')"
check "afya_app INSERT audit_log without at/id (column grant)" app_psql "INSERT INTO afya.audit_log (kind, actor, auth, visit_id, run_id, payload) VALUES ('smoke', 'nurse-a', 'demo_switcher', NULL, NULL, '{}')"
refuse "afya_app cannot set audit_log.at (column grant)" app_psql "INSERT INTO afya.audit_log (at, kind, actor, payload) VALUES (now(), 'smoke', 'nurse-a', '{}')"
refuse "afya_app nextval on audit_log sequence denied" app_psql "SELECT nextval(pg_get_serial_sequence('afya.audit_log', 'id'))"
check "afya_app INSERT on lg.checkpoints" test "$(app_atc "select has_table_privilege('afya_app','lg.checkpoints','INSERT')")" = t
check "afya_app no TRUNCATE on lg.checkpoints" test "$(app_atc "select has_table_privilege('afya_app','lg.checkpoints','TRUNCATE')")" = f
check "PUBLIC has no TEMP on afya" test "$(dc exec -T postgres psql -U "$PG_SUPERUSER" -d afya -Atc "select has_database_privilege('afya_app','afya','TEMP')" | tr -d '\r')" = f
# Every row this script leaves in the stack's database is tagged: visit ids start with "synthetic-smoke-", patient labels
# with "SMOKE-", idempotency keys with "smoke-". To start empty: see db/README.md (docker compose down -v wipes ALL data).
SMOKE_ID="synthetic-smoke-$(date +%s)-$$"
app_psql "INSERT INTO afya.visits (id, patient_id, latest_obs_id) VALUES ('$SMOKE_ID', 'p', 'o1'); INSERT INTO afya.proposals (visit_id, trigger, evidence_hash, obs_id, payload) VALUES ('$SMOKE_ID', 'colour_rise', 'h', 'o1', '{}')" >/dev/null 2>&1 && ok "smoke visit and proposal created" || bad "smoke visit and proposal created"
# approve + command in ONE statement (CTE): the database refuses an approved proposal without a command
APPROVE="WITH a AS (UPDATE afya.proposals p SET status='approved', decided_by='%s', decided_at=now() FROM afya.users u WHERE p.visit_id='$SMOKE_ID' AND p.status='pending' AND u.id='%s' AND u.role IN ('nurse','clinician') RETURNING p.*) INSERT INTO afya.commands (proposal_id, visit_id, obs_id, colour, evidence_hash, expires_at) SELECT id, visit_id, obs_id, 'RED', evidence_hash, now() + interval '1 hour' FROM a RETURNING proposal_id"
refuse "proposals_guard: manager cannot approve (direct UPDATE)" app_psql "UPDATE afya.proposals SET status='approved', decided_by='mgr-k', decided_at=now() WHERE visit_id='$SMOKE_ID'"
check "approve query by nurse -> 1 row" test "$(app_atc "$(printf "$APPROVE" nurse-a nurse-a)" | grep -cE '^[0-9a-f-]{36}$')" = 1
check "approve query a second time -> 0 rows" test "$(app_atc "$(printf "$APPROVE" nurse-a nurse-a)" | grep -cE '^[0-9a-f-]{36}$')" = 0
refuse "proposals_guard: approved proposal cannot be re-decided" app_psql "UPDATE afya.proposals SET status='rejected' WHERE visit_id='$SMOKE_ID'"
refuse "commands: done_at without claimed_at refused" app_psql "UPDATE afya.commands SET done_at = now() WHERE visit_id='$SMOKE_ID'"
refuse "afya_app cannot rewrite an approved proposal's payload (column grants)" app_psql "UPDATE afya.proposals SET payload = '{}' WHERE visit_id='$SMOKE_ID'"
refuse "afya_app cannot rewrite a command's colour or expiry (column grants)" app_psql "UPDATE afya.commands SET colour = 'GREEN' WHERE visit_id='$SMOKE_ID'"
refuse "a command for a proposal that is not approved is refused" app_psql "INSERT INTO afya.proposals (visit_id, trigger, evidence_hash, obs_id, payload) VALUES ('$SMOKE_ID', 'x', 'h2', 'o1', '{}'); INSERT INTO afya.commands (proposal_id, visit_id, obs_id, colour, evidence_hash, expires_at) SELECT id, visit_id, obs_id, 'RED', evidence_hash, now() FROM afya.proposals WHERE visit_id='$SMOKE_ID' AND trigger='x'"
check "schema_version recorded" test "$(app_atc "select max(version) from afya.schema_version")" -ge 2
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
# E12-3: WSO2 (authorization disabled) is on "borrowed" with the api only; afya-mcp's mounts need the bearer token
check "wso2-fhir-mcp cannot resolve afya-mcp" dc exec -T wso2-fhir-mcp python -c "
import socket,sys
try: socket.gethostbyname('afya-mcp')
except socket.gaierror: sys.exit(0)
sys.exit(1)"
check "afya-mcp cannot resolve wso2-fhir-mcp" dc exec -T afya-mcp python -c "
import socket,sys
try: socket.gethostbyname('wso2-fhir-mcp')
except socket.gaierror: sys.exit(0)
sys.exit(1)"
MCP_INIT="{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'smoke','version':'1'}}}"
for m in act ui read; do
  check "afya-mcp /$m without the token -> 401" dc exec -T api python -c "
import httpx,sys
r=httpx.post('http://afya-mcp:9000/$m/mcp',headers={'Accept':'application/json, text/event-stream'},json=$MCP_INIT)
sys.exit(0 if r.status_code==401 else 1)"
  check "afya-mcp /$m with a wrong token -> 401" dc exec -T api python -c "
import httpx,sys
r=httpx.post('http://afya-mcp:9000/$m/mcp',headers={'Accept':'application/json, text/event-stream','Authorization':'Bearer wrong'},json=$MCP_INIT)
sys.exit(0 if r.status_code==401 else 1)"
done
check "afya-mcp /act with the api's token -> initialize ok" dc exec -T api python -c "
import httpx,sys,os
r=httpx.post('http://afya-mcp:9000/act/mcp',headers={'Accept':'application/json, text/event-stream','Authorization':'Bearer '+os.environ['AFYA_MCP_TOKEN']},json=$MCP_INIT)
sys.exit(0 if r.status_code==200 and 'serverInfo' in r.text else 1)"
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
check "compute_tews on seeded Patient+Encounter+Observation (audited as agent)" mcpx <<'PY'
import asyncio, os, sys, uuid, httpx
from datetime import date, timedelta
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from afya_mcp.fhir import vitals_observation

H = {"Content-Type": "application/fhir+json"}
F = "http://hapi:8080/fhir"
def post(res):
    r = httpx.post(f"{F}/{res['resourceType']}", json=res, headers=H, timeout=30); r.raise_for_status(); return r.json()["id"]

born = (date.today() - timedelta(days=365 * 40)).isoformat()
pid = post({"resourceType": "Patient", "identifier": [{"system": "urn:afya:label", "value": "SMOKE-" + uuid.uuid4().hex[:8]}], "birthDate": born, "gender": "other"})
eid = post({"resourceType": "Encounter", "status": "in-progress", "class": {"code": "EMER"}, "subject": {"reference": f"Patient/{pid}"}})
obs = vitals_observation(pid, eid, {"resp_rate": 26, "heart_rate": 118, "systolic_bp": 95, "temperature": 38.6,
                                     "spo2": 93, "mobility": "walking", "consciousness": "alert", "trauma": "no"},
                         "smoke-" + uuid.uuid4().hex)
oid = post(obs)

async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/read/mcp/", headers={"Authorization": "Bearer " + os.environ["AFYA_MCP_TOKEN"]}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("compute_tews", {"observation_id": f"Observation/{oid}"})
            print(res.structuredContent or res.content)
            return not res.isError and "scored" in str(res.structuredContent or res.content)
sys.exit(0 if asyncio.run(main()) else 1)
PY

check "api imports afya_mcp.workflow (shared SQL module)" dc exec -T api python -c "import afya_mcp.workflow, afya_mcp.db"
check "record_vitals via /act/mcp sets visits.latest_obs_id and writes one audit row" mcpx <<'PY'
import asyncio, json, os, sys, uuid, httpx, psycopg
from datetime import date, timedelta
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

H = {"Content-Type": "application/fhir+json"}
F = "http://hapi:8080/fhir"
def post(res):
    r = httpx.post(f"{F}/{res['resourceType']}", json=res, headers=H, timeout=30); r.raise_for_status(); return r.json()["id"]

pid = post({"resourceType": "Patient", "identifier": [{"system": "urn:afya:label", "value": "SMOKE-" + uuid.uuid4().hex[:8]}], "birthDate": (date.today() - timedelta(days=365 * 40)).isoformat(), "gender": "other"})
eid = post({"resourceType": "Encounter", "status": "in-progress", "class": {"code": "EMER"}, "subject": {"reference": f"Patient/{pid}"}})
values = {"resp_rate": 16, "heart_rate": 80, "systolic_bp": 120, "temperature": 37.0, "mobility": "walking",
          "consciousness": "alert", "trauma": "no"}

async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/act/mcp/", headers={"Authorization": "Bearer " + os.environ["AFYA_MCP_TOKEN"]}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("record_vitals", {"patient_id": pid, "visit_id": eid, "values": values,
                                                      "idempotency_key": "smoke-" + uuid.uuid4().hex,
                                                      "actor": "nurse-a"})
            return json.loads(res.content[0].text)["observation_id"].split("/")[1]

oid = asyncio.run(main())
with psycopg.connect(os.environ["DATABASE_URL"]) as c:
    row = c.execute("select latest_obs_id, patient_id from visits where id = %s", (eid,)).fetchone()
    audited = c.execute("select count(*) from audit_log where kind = 'record_vitals' and actor = 'nurse-a' "
                        "and visit_id = %s and payload ? 'latency_ms'", (eid,)).fetchone()[0]
sys.exit(0 if row == (oid, pid) and audited == 1 else 1)
PY

check "get_queue_state via /read/mcp lists a seeded visit with minutes waited vs SATS target" mcpx <<'PY'
import asyncio, json, os, sys, uuid, httpx
from datetime import date, datetime, timedelta, timezone
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

H = {"Content-Type": "application/fhir+json"}
F = "http://hapi:8080/fhir"
def post(res):
    r = httpx.post(f"{F}/{res['resourceType']}", json=res, headers=H, timeout=30); r.raise_for_status(); return r.json()["id"]

pid = post({"resourceType": "Patient", "identifier": [{"system": "urn:afya:label", "value": "SMOKE-" + uuid.uuid4().hex[:8]}], "birthDate": (date.today() - timedelta(days=365 * 40)).isoformat(), "gender": "other"})
start = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
eid = post({"resourceType": "Encounter", "status": "arrived", "class": {"code": "EMER"}, "subject": {"reference": f"Patient/{pid}"},
            "period": {"start": start}, "priority": {"coding": [{"system": "urn:afya:sats-colour", "code": "ORANGE"}]}})

async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/read/mcp/", headers={"Authorization": "Bearer " + os.environ["AFYA_MCP_TOKEN"]}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("get_queue_state", {})
            return json.loads(res.content[0].text)

q = asyncio.run(main())
mine = [p for p in q["patients"] if p["visit_id"] == eid]
ok = (len(mine) == 1 and mine[0]["target_minutes"] == 10 and mine[0]["minutes_waited"] >= 29
      and mine[0]["over_target"] and mine[0]["recheck"]["overdue"] and isinstance(q["proposals"], list))
print(mine)
sys.exit(0 if ok else 1)
PY

check "approve -> raise_recheck_flag via /act/mcp: one Flag in HAPI, Encounter.priority set, audit rows (retry safe)" mcpx <<'PY'
import asyncio, json, os, sys, uuid, httpx
from datetime import date, timedelta
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from afya_mcp import db, workflow

H = {"Content-Type": "application/fhir+json"}
F = "http://hapi:8080/fhir"
def post(res):
    r = httpx.post(f"{F}/{res['resourceType']}", json=res, headers=H, timeout=30); r.raise_for_status(); return r.json()["id"]

pid = post({"resourceType": "Patient", "identifier": [{"system": "urn:afya:label", "value": "SMOKE-" + uuid.uuid4().hex[:8]}], "birthDate": (date.today() - timedelta(days=365 * 40)).isoformat(), "gender": "other"})
eid = post({"resourceType": "Encounter", "status": "in-progress", "class": {"code": "EMER"}, "subject": {"reference": f"Patient/{pid}"},
            "priority": {"coding": [{"system": "urn:afya:sats-colour", "code": "YELLOW"}]}})
values = {"resp_rate": 26, "heart_rate": 118, "systolic_bp": 95, "temperature": 38.6, "mobility": "walking",
          "consciousness": "alert", "trauma": "no"}

async def act(session, tool, args):
    res = await session.call_tool(tool, args)
    return res.isError, (json.loads(res.content[0].text) if not res.isError else res.content[0].text)

async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/act/mcp/", headers={"Authorization": "Bearer " + os.environ["AFYA_MCP_TOKEN"]}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            _, saved = await act(s, "record_vitals", {"patient_id": pid, "visit_id": eid, "values": values,
                                                      "idempotency_key": "smoke-" + uuid.uuid4().hex, "actor": "nurse-a"})
            oid = saved["observation_id"].split("/")[1]
            with db.connect() as c:
                p = workflow.insert_proposal(c, eid, "colour_rise", oid, workflow.evidence_hash([oid], [], "sats_adult_2012"),
                                             {"to_colour": "ORANGE", "cited_obs_ids": [oid]})
                cid = str(workflow.approve_proposal(c, str(p["id"]), "nurse-a")["command"]["id"])
            refused, _ = await act(s, "raise_recheck_flag", {"command_id": cid, "actor": "mgr-k"})
            _, first = await act(s, "raise_recheck_flag", {"command_id": cid, "actor": "nurse-a", "run_id": "smoke-run"})
            _, again = await act(s, "raise_recheck_flag", {"command_id": cid, "actor": "nurse-a", "run_id": "smoke-run"})
            return cid, refused, first, again

cid, refused, first, again = asyncio.run(main())
flags = httpx.get(f"{F}/Flag", params={"identifier": f"urn:afya:command|{cid}"}, timeout=30).json().get("entry", [])
enc = httpx.get(f"{F}/Encounter/{eid}", timeout=30).json()
colour = [c["code"] for c in enc.get("priority", {}).get("coding", []) if c.get("system") == "urn:afya:sats-colour"]
with db.connect() as c:
    kinds = [r["kind"] for r in c.execute("SELECT kind FROM audit_log WHERE visit_id = %s ORDER BY id", (eid,))]
    kinds += [r["kind"] for r in c.execute("SELECT kind FROM audit_log WHERE kind = 'raise_recheck_flag_refused' "
                                           "AND actor = 'mgr-k' AND payload->'inputs'->>'command_id' = %s", (cid,))]
print(first, again, len(flags), colour, kinds)
ok = (refused and first["status"] == "done" and again["status"] == "already_done" and len(flags) == 1
      and first["flag_id"] == again["flag_id"] == f"Flag/{flags[0]['resource']['id']}" and colour == ["ORANGE"]
      and kinds.count("command_done") == 1 and kinds.count("raise_recheck_flag") == 2
      and {"record_vitals", "proposal_approved", "raise_recheck_flag_refused"} <= set(kinds))
sys.exit(0 if ok else 1)
PY

check "notify_staff via /act/mcp stores a fixed-text notification and an audit row" mcpx <<'PY'
import asyncio, json, os, sys, uuid
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from afya_mcp import db

visit = "synthetic-smoke-" + uuid.uuid4().hex[:12]

async def main():
    async with streamablehttp_client("http://127.0.0.1:9000/act/mcp/", headers={"Authorization": "Bearer " + os.environ["AFYA_MCP_TOKEN"]}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("notify_staff", {"kind": "vitals_due", "visit_id": visit, "actor": "agent"})
            return json.loads(res.content[0].text)

out = asyncio.run(main())
with db.connect() as c:
    row = c.execute("SELECT kind, target_role, text FROM notifications WHERE id = %s", (out["notification_id"],)).fetchone()
    audited = c.execute("SELECT count(*) AS n FROM audit_log WHERE kind = 'notify_staff' AND actor = 'agent' "
                        "AND visit_id = %s", (visit,)).fetchone()["n"]
print(out, row, audited)
sys.exit(0 if out["status"] == "sent" and row["kind"] == "vitals_due" and row["text"] == out["text"]
         and audited == 1 else 1)
PY
check "afya_app can only acknowledge notifications (no UPDATE of text, no DELETE)" test "$(app_atc "select has_column_privilege('afya_app','afya.notifications','acknowledged_at','UPDATE'), has_column_privilege('afya_app','afya.notifications','text','UPDATE'), has_table_privilege('afya_app','afya.notifications','DELETE')")" = "t|f|f"

echo "== api end to end (E5/E6): P-014 second reading -> agent run -> exactly one proposal -> approve -> Flag in HAPI"
API_OUT=$(dc exec -T api python - <<'PY' 2>/dev/null
# In-process client of the real app against the real afya-mcp, WSO2, HAPI, Postgres and model (whatever its state:
# with the model down the run goes on with the rules only). current_user (E6-2, B) is replaced by an override, so this
# runs without a session cookie. The agent run starts after POST /vitals answers; TestClient waits for it.
# Model-agnostic: nothing below depends on what the model said.
import sys, uuid
from fastapi.testclient import TestClient
from afya_mcp import db
from afya_api import deps
from afya_api.main import app

app.dependency_overrides[deps.current_user] = lambda: deps.User(id="nurse-a", name="Nurse A.", role="nurse")
def need(ok, what):
    if not ok:
        print("FAILED:", what); sys.exit(1)
with TestClient(app) as c:
    r = c.post("/demo/scenario", json={"name": "p014"}); need(r.status_code == 200, f"scenario {r.text}")
    visit = r.json()["visit_id"]
    r = c.post("/vitals", json={"visit_id": visit, "idempotency_key": "smoke-" + uuid.uuid4().hex, "resp_rate": 26,
                                "heart_rate": 112, "systolic_bp": 120, "temperature": 38.6, "spo2": 93,
                                "mobility": "walking", "consciousness": "alert", "trauma": "no",
                                "complaint": "Short of breath since morning. My mother had chest pain last year."})
    need(r.status_code == 200 and r.json()["status"] == "saved", f"vitals {r.text}")
    obs = r.json()["observation_id"]; oid = obs.split("/")[1]; run_id = r.json()["run_id"]
    need(run_id == f"{visit}:{oid}", "run id")
    tl = c.get(f"/visits/{visit}/timeline").json()
    need([(x["tews"], x["colour"]) for x in tl["readings"]] == [(3, "YELLOW"), (6, "ORANGE")], f"timeline {tl}")
    mine = [x for x in c.get("/proposals").json() if x["visit_id"] == visit]
    need(len(mine) == 1, f"exactly one proposal for the visit, got {len(mine)}")
    p = mine[0]
    need(p["obs_id"] == obs and p["trigger"] == "colour_rise" and p["current_colour"] == "YELLOW"
         and p["proposed_colour"] == "ORANGE" and p["tews_before"] == 3 and p["tews_after"] == 6
         and p["patient_label"] == "P-014" and p["complaint"].startswith("Short of breath")
         and p["rationale_source"] in ("model", "code") and p["agent_action"] in
         ("propose", "propose_and_remeasure", "request_missing_value"), f"proposal {p}")
    need({"heart_rate", "temperature"} <= {e["input"] for e in p["evidence"] if e["band_changed"]}, "evidence rows")
    steps = [(s["kind"], s["name"]) for s in c.get(f"/runs/{run_id}/trace").json()]
    need({("tool", "compute_tews"), ("tool", "check_deterioration"), ("decision", "trigger"),
          ("decision", "submit_decision"), ("gate", "paused_for_nurse")} <= set(steps), f"trace {steps}")
    with db.connect() as conn:
        n = conn.execute("SELECT count(*) AS n FROM lg.checkpoints WHERE thread_id = %s", (run_id,)).fetchone()["n"]
    need(n > 0, "checkpoints in schema lg")
    pid = p["id"]
    r = c.post(f"/proposals/{pid}/approve", json={"colour": "ORANGE", "signs_kept": []})
    need(r.status_code == 200, f"approve {r.text}")
    cid = r.json()["command_id"]
    gates = {g["gate"]: g for g in c.get(f"/proposals/{pid}/gates").json()}
    need(all(gates[g]["at"] for g in gates), f"gates {gates}")
    steps = [(s["kind"], s["name"]) for s in c.get(f"/runs/{run_id}/trace").json()]
    need(("tool", "raise_recheck_flag") in steps, "the executor ran inside the resumed run")
    print(visit, cid)
PY
)
API_VISIT=$(echo "$API_OUT" | tail -1 | tr -d '\r' | cut -d' ' -f1); API_CMD=$(echo "$API_OUT" | tail -1 | tr -d '\r' | cut -d' ' -f2)
check "api: P-014 second reading -> agent run -> exactly one proposal; approve resumes it; gates ticked" test "$(echo "$API_CMD" | grep -cE '^[0-9a-f-]{36}$')" = 1
check "api approve -> exactly one Flag in HAPI and Encounter.priority ORANGE" mcpx "$API_VISIT" "$API_CMD" <<'PY'
import sys, httpx
visit, cid = sys.argv[1], sys.argv[2]
F = "http://hapi:8080/fhir"
flags = httpx.get(f"{F}/Flag", params={"identifier": f"urn:afya:command|{cid}"}, timeout=30).json().get("entry", [])
enc = httpx.get(f"{F}/Encounter/{visit}", timeout=30).json()
colour = [c["code"] for c in enc.get("priority", {}).get("coding", []) if c.get("system") == "urn:afya:sats-colour"]
print(len(flags), colour)
sys.exit(0 if len(flags) == 1 and colour == ["ORANGE"] else 1)
PY

echo "== host exposure"
PUB=$(docker ps --filter "label=com.docker.compose.project=afya" --format '{{.Names}} {{.Ports}}' | grep -E '0\.0\.0\.0|\[::\]|127\.0\.0\.1' || true)
# With the web profile up, the only allowed one is the web UI on the loopback (127.0.0.1:3000).
OTHER=$(printf '%s\n' "$PUB" | grep -vE '^afya-web-1 127\.0\.0\.1:3000->3000/tcp$' | grep . || true)
if [ -z "$PUB" ]; then ok "no service publishes a host port (web profile off)"
elif [ -z "$OTHER" ]; then ok "only the web UI publishes a port, on 127.0.0.1:3000 (web profile on)"
else bad "published ports: $OTHER"; fi
check "compose publishes only 127.0.0.1:3000" test "$(dc --profile web config | grep -cE 'published:')" -le 1

echo
if [ "$FAILS" -eq 0 ]; then echo "SMOKE OK"; else echo "SMOKE FAILED: $FAILS check(s)"; exit 1; fi
