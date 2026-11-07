"""E13-3: afya-mcp as an OAuth 2.1 protected resource (MCP authorization, protocol 2026-07-28).

Raw HTTP over a private copy of the server app (a session manager runs once per process). Tokens are signed with the
local test key (oauth_fixture.py); no authorization server and no network are needed."""
import importlib.util
import io
import json

import jwt
import pytest
from starlette.testclient import TestClient

from afya_mcp import auth
from oauth_fixture import BASE, ISSUER, OTHER_KEY, SCOPES, bearer, mint

ACCEPT = {"Accept": "application/json, text/event-stream"}
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
TOOLS = {"read": {"compute_tews", "check_deterioration", "get_queue_state"},
         "act": {"record_vitals", "raise_recheck_flag", "notify_staff", "seed_demo_visit"},
         "ui": {"visit_timeline", "queue_state", "demo_visit"}}
MOUNTS = list(TOOLS)


@pytest.fixture(scope="module")
def client():
    from afya_mcp import server as real
    spec = importlib.util.spec_from_file_location("afya_mcp._server_auth_copy", real.__file__)
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    server._fhir = lambda: pytest.fail("a refused request must not reach FHIR")
    with TestClient(server.app, base_url="http://afya-mcp:9000") as c:
        yield c


def post(c, mount, headers=None):
    return c.post(f"/{mount}/mcp", json=LIST, headers={**ACCEPT, **(headers or {})})


def challenge(r) -> dict[str, str]:
    value = r.headers["www-authenticate"]
    assert value.startswith("Bearer")
    out = {}
    for part in value.removeprefix("Bearer").strip().split(", "):
        if part:
            k, v = part.split("=", 1)
            out[k] = v.strip('"')
    return out


def tool_names(r) -> set[str]:
    data = next(json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:"))
    return {t["name"] for t in data["result"]["tools"]}


# ---------- protected-resource metadata (RFC 9728) ----------

@pytest.mark.parametrize("mount", MOUNTS)
def test_protected_resource_metadata_per_mount(client, mount):
    r = client.get(f"/.well-known/oauth-protected-resource/{mount}/mcp")   # public: no token
    assert r.status_code == 200
    meta = r.json()
    assert meta["resource"] == f"{BASE}/{mount}/mcp"
    assert meta["authorization_servers"] == [ISSUER]           # exactly the issuer (RFC 8414 string comparison)
    assert meta["scopes_supported"] == [SCOPES[mount]]     # least privilege: only this mount's scope
    assert meta["bearer_methods_supported"] == ["header"]  # never a token in the URL or the body
    for forbidden in ("Patient/", "Encounter/", "Observation/", "postgres", "hapi"):
        assert forbidden not in r.text


# ---------- 401: missing, malformed, bad signature, expired, wrong audience, wrong issuer ----------

@pytest.mark.parametrize("mount", MOUNTS)
def test_missing_token_is_401_with_resource_metadata_and_scope(client, mount):
    r = post(client, mount)
    assert r.status_code == 401
    ch = challenge(r)
    assert ch["resource_metadata"] == f"{BASE}/.well-known/oauth-protected-resource/{mount}/mcp"
    assert ch["scope"] == SCOPES[mount]
    assert "error" not in ch   # RFC 6750 §3.1: no error code without credentials


def _bad_tokens(mount):
    other = {"read": "act", "act": "ui", "ui": "read"}[mount]
    return {
        "not a JWT": "not-a-jwt",
        "invalid signature": mint(mount, key=OTHER_KEY),
        "tampered payload": mint(mount)[:-8] + "AAAAAAAA",
        "expired": mint(mount, expires_in=-120),
        "wrong audience (another mount)": mint(mount, aud=f"{BASE}/{other}/mcp"),
        "wrong audience (another server)": mint(mount, aud="http://evil.example/mcp"),
        "no audience": mint(mount, drop=("aud",)),
        "wrong issuer": mint(mount, iss="https://evil.example"),
        "no expiry": mint(mount, drop=("exp",)),
        "not an access token (typ JWT)": mint(mount, typ="JWT"),
        "HS256 (shared secret)": jwt.encode({"iss": ISSUER, "aud": f"{BASE}/{mount}/mcp", "sub": "x", "exp": 2**31,
                                             "iat": 1, "scope": SCOPES[mount]}, "s" * 32, algorithm="HS256",
                                            headers={"typ": "at+jwt"}),
        "unsigned (alg none)": jwt.encode({"iss": ISSUER, "aud": f"{BASE}/{mount}/mcp", "sub": "x", "exp": 2**31,
                                           "iat": 1, "scope": SCOPES[mount]}, None, algorithm="none",
                                          headers={"typ": "at+jwt"}),
    }


@pytest.mark.parametrize("mount", MOUNTS)
def test_invalid_tokens_are_401_invalid_token(client, mount):
    for name, token in _bad_tokens(mount).items():
        r = post(client, mount, bearer(token))
        assert r.status_code == 401, (mount, name, r.status_code)
        ch = challenge(r)
        assert ch["error"] == "invalid_token", (mount, name)
        assert ch["resource_metadata"].endswith(f"/.well-known/oauth-protected-resource/{mount}/mcp")
        assert token not in r.text and token not in r.headers["www-authenticate"]


@pytest.mark.parametrize("mount", MOUNTS)
def test_other_schemes_and_query_tokens_are_refused(client, mount):
    token = mint(mount)
    assert post(client, mount, {"Authorization": f"Basic {token}"}).status_code == 401
    assert post(client, mount, {"Authorization": token}).status_code == 401
    r = client.post(f"/{mount}/mcp?access_token={token}", json=LIST, headers=ACCEPT)   # never from the URL
    assert r.status_code == 401


# ---------- 403: valid token, insufficient scope ----------

@pytest.mark.parametrize("mount", MOUNTS)
def test_insufficient_scope_is_403_with_the_required_scope(client, mount):
    others = [s for m, s in SCOPES.items() if m != mount]
    for scope in ("", " ".join(others), ["openid"]):
        r = post(client, mount, bearer(mint(mount, scope=scope)))
        assert r.status_code == 403, (mount, scope)
        ch = challenge(r)
        assert ch["error"] == "insufficient_scope" and ch["scope"] == SCOPES[mount]
        assert ch["resource_metadata"].endswith(f"/.well-known/oauth-protected-resource/{mount}/mcp")


@pytest.mark.parametrize("mount", ["act", "ui"])
def test_a_read_token_is_refused_by_the_other_mounts(client, mount):
    """Least privilege: the model-facing path's token (read scope, read audience) is refused by /act and /ui."""
    assert post(client, mount, bearer(mint("read"))).status_code == 401              # audience is /read/mcp
    # even a token for this audience but only the read scope is not enough
    assert post(client, mount, bearer(mint(mount, scope="afya:read"))).status_code == 403


# ---------- success ----------

@pytest.mark.parametrize("mount", MOUNTS)
def test_valid_token_lists_the_mounts_tools(client, mount):
    r = post(client, mount, bearer(mint(mount)))
    assert r.status_code == 200, r.text
    assert tool_names(r) == TOOLS[mount]


@pytest.mark.parametrize("mount", MOUNTS)
def test_authelia_style_scp_list_and_several_audiences_are_accepted(client, mount):
    token = mint(mount, scope=[SCOPES[mount], "afya:other"], aud=[f"{BASE}/{mount}/mcp", "http://another/mcp"])
    assert post(client, mount, bearer(token)).status_code == 200


def test_small_clock_skew_on_nbf_is_tolerated_but_expiry_is_strict(client):
    """An authorization server clock a little ahead is fine (nbf/iat leeway); an expired token never is (the SDK
    re-checks exp without leeway)."""
    import time
    ahead = int(time.time()) + auth.LEEWAY - 10
    assert post(client, "read", bearer(mint("read", nbf=ahead, iat=ahead))).status_code == 200
    assert post(client, "read", bearer(mint("read", expires_in=-5))).status_code == 401


def test_host_and_origin_checks_still_apply_after_authorization(client):
    token = mint("read")
    r = client.post("http://evil.example:9000/read/mcp", json=LIST, headers={**ACCEPT, **bearer(token)})
    assert r.status_code == 421
    r = post(client, "read", {**bearer(token), "Origin": "http://evil.example"})
    assert r.status_code == 403 and "www-authenticate" not in r.headers   # transport refusal, not an auth one


def test_healthz_stays_open(client):
    assert client.get("/healthz").text == "ok"


# ---------- fail closed, logging, key discovery ----------

def test_without_an_issuer_every_mount_refuses(monkeypatch):
    v = auth.JwtVerifier("", f"{BASE}/read/mcp", lambda _t: pytest.fail("no key lookup without an issuer"))
    assert __import__("asyncio").run(v.verify_token(mint("read"))) is None


def test_refusals_never_log_the_token(client, caplog):
    caplog.set_level("DEBUG")
    for token in _bad_tokens("read").values():
        post(client, "read", bearer(token))
    good = mint("read")
    post(client, "read", bearer(good))
    for token in [*_bad_tokens("read").values(), good]:
        assert token not in caplog.text


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_issuer_keys_use_rfc8414_metadata_and_refuse_another_issuer(monkeypatch):
    seen = []

    def urlopen(url, timeout, context):
        seen.append(url)
        return _Resp(json.dumps({"issuer": "https://evil.example", "jwks_uri": "https://evil.example/jwks"}).encode())

    monkeypatch.setattr(auth.urllib.request, "urlopen", urlopen)
    keys = auth.IssuerKeys(ISSUER, None)
    with pytest.raises(ValueError, match="another issuer"):
        keys._jwks()
    assert seen == [f"{ISSUER}/.well-known/oauth-authorization-server"]
    assert keys._client is None   # a failure is not cached


def test_issuer_keys_verify_with_the_jwks_from_the_metadata(monkeypatch):
    from oauth_fixture import KEY
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
    jwk.update(kid="test-1", use="sig", alg="RS256")
    monkeypatch.setattr(auth.urllib.request, "urlopen", lambda url, timeout, context: _Resp(json.dumps(
        {"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks.json"}).encode()))
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: {"keys": [jwk]})
    keys = auth.IssuerKeys(ISSUER, None)
    v = auth.JwtVerifier(ISSUER, f"{BASE}/read/mcp", keys.key)
    run = __import__("asyncio").run
    token = run(v.verify_token(mint("read")))
    assert token is not None and token.scopes == ["afya:read"] and token.client_id == "afya-api"
    assert token.resource == f"{BASE}/read/mcp" and token.expires_at
    assert run(v.verify_token(mint("read", key=OTHER_KEY))) is None
