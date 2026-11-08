"""E13-3: afya-mcp as an OAuth 2.1 protected resource (MCP authorization, protocol 2026-07-28).

Each mount is its own protected resource with its own audience and scope:

    resource (RFC 8707 / RFC 9728)        scope       caller
    <base>/read/mcp                       afya:read   the agent's model-facing read path
    <base>/act/mcp                        afya:act    fixed code only (executor after approval, vitals, notices)
    <base>/ui/mcp                         afya:ui     the api's screens

<base> is AFYA_MCP_RESOURCE_BASE (compose: https://afya-mcp:9000). Tokens are JWT access tokens (RFC 9068) signed by
the authorization server named in AFYA_AUTH_ISSUER (Authelia in compose). A token is accepted only if its signature
checks against the issuer's JWKS (found through RFC 8414 metadata, fetched over TLS with AFYA_AUTH_CA_FILE), its
`iss` is exactly the issuer, its `aud` contains this mount's resource, it has not expired, its `typ` is at+jwt and it
carries this mount's scope. The SDK does the rest: `BearerAuthBackend` (resource check), `RequireAuthMiddleware`
(401 invalid_token / 403 insufficient_scope with `resource_metadata`) and `create_protected_resource_routes`
(RFC 9728 metadata at /.well-known/oauth-protected-resource/<mount>/mcp, the only unauthenticated MCP-related path).

Never logged: a token, a claim value or a key. Never forwarded: afya-mcp calls HAPI without any credential.
Without AFYA_AUTH_ISSUER every mount answers 401 (fail closed).
"""
from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import anyio
import jwt
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.routes import build_resource_metadata_url, create_protected_resource_routes
from pydantic import AnyHttpUrl
from starlette.requests import HTTPConnection
from starlette.routing import Route

log = logging.getLogger("afya_mcp.auth")

SCOPES = {"read": "afya:read", "act": "afya:act", "ui": "afya:ui"}
ALGORITHMS = ["RS256", "PS256", "ES256"]       # asymmetric only: never HS* (a shared secret) and never "none"
TOKEN_TYPES = {"at+jwt", "application/at+jwt"}  # RFC 9068 §2.1: refuses ID tokens and other JWTs
LEEWAY = 30                                     # seconds of clock skew on nbf/iat (the SDK re-checks exp strictly)
NAMES = {"read": "Afya Triage Watch read tools", "act": "Afya Triage Watch gated actions",
         "ui": "Afya Triage Watch screen data"}


@dataclass(frozen=True)
class Settings:
    issuer: str            # exact issuer identifier (RFC 8414 / RFC 9207 string comparison), "" = fail closed
    base: str              # canonical base URI of this server, no trailing slash
    ca_file: str | None    # CA bundle for the authorization server's TLS certificate (None: system store)

    def resource(self, mount: str) -> str:
        return f"{self.base}/{mount}/mcp"

    def metadata_url(self, mount: str) -> str:
        return str(build_resource_metadata_url(AnyHttpUrl(self.resource(mount))))


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings(issuer=os.environ.get("AFYA_AUTH_ISSUER", "").strip(),
                    base=os.environ.get("AFYA_MCP_RESOURCE_BASE", "https://afya-mcp:9000").strip().rstrip("/"),
                    ca_file=os.environ.get("AFYA_AUTH_CA_FILE") or None)


class IssuerKeys:
    """The issuer's signing keys: RFC 8414 metadata -> `jwks_uri` -> PyJWKClient (cached, refetched on an unknown
    `kid`, at most once per cooldown). Blocking urllib, so it runs in a worker thread. A failed lookup is not cached:
    the next request tries again (the authorization server may start after afya-mcp)."""

    def __init__(self, issuer: str, ca_file: str | None) -> None:
        self.issuer, self.ca_file = issuer, ca_file
        self._client: jwt.PyJWKClient | None = None
        self._lock = threading.Lock()

    def _ssl(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=self.ca_file)

    def _jwks(self) -> jwt.PyJWKClient:
        with self._lock:
            if self._client is None:
                url = self.issuer + "/.well-known/oauth-authorization-server"
                with urllib.request.urlopen(url, timeout=10, context=self._ssl()) as r:   # noqa: S310 (https issuer)
                    meta = json.load(r)
                if meta.get("issuer") != self.issuer:   # RFC 8414 §3.3: never use metadata of another issuer
                    raise ValueError("authorization server metadata names another issuer")
                self._client = jwt.PyJWKClient(meta["jwks_uri"], cache_jwk_set=True, lifespan=300, timeout=10,
                                               ssl_context=self._ssl())
            return self._client

    def _key(self, token: str) -> Any:
        return self._jwks().get_signing_key_from_jwt(token).key

    async def key(self, token: str) -> Any:
        return await anyio.to_thread.run_sync(self._key, token)


@lru_cache(maxsize=1)
def _keys() -> IssuerKeys:
    s = settings()
    return IssuerKeys(s.issuer, s.ca_file)


def _scopes(claims: dict[str, Any]) -> list[str]:
    """RFC 9068 `scope` (space-separated string); Authelia sends `scp` (a list) instead."""
    if isinstance(claims.get("scope"), str):
        return claims["scope"].split()
    scp = claims.get("scp")
    return [s for s in scp if isinstance(s, str)] if isinstance(scp, list) else []


class JwtVerifier:
    """The SDK's TokenVerifier for one mount: an AccessToken for a valid token, None otherwise (-> 401).

    `keys(token)` returns the verification key; it is IssuerKeys.key in the service and a local test key in the tests
    (no network). `resource` is set to this mount's resource only after `aud` was checked, so the SDK's own resource
    check (BearerAuthBackend with resource_server_url) agrees."""

    def __init__(self, issuer: str, resource: str, keys: Callable[[str], Any]) -> None:
        self.issuer, self.resource, self.keys = issuer, resource, keys

    async def verify_token(self, token: str) -> AccessToken | None:
        if not self.issuer:
            return None
        try:
            header = jwt.get_unverified_header(token)
            if str(header.get("typ", "")).lower() not in TOKEN_TYPES or header.get("alg") not in ALGORITHMS:
                raise jwt.InvalidTokenError("not an RFC 9068 access token")
            key = await self.keys(token)
            claims = jwt.decode(token, key, algorithms=ALGORITHMS, audience=self.resource, issuer=self.issuer,
                                leeway=LEEWAY, options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        except Exception as e:   # noqa: BLE001 - any failure is a refusal; only the class name is logged
            log.info("access token refused: %s", type(e).__name__)
            return None
        return AccessToken(token=token, client_id=str(claims.get("client_id") or claims["sub"]),
                           scopes=_scopes(claims), expires_at=int(claims["exp"]), resource=self.resource,
                           subject=str(claims["sub"]), claims={"iss": claims["iss"]})


def verifier(mount: str) -> JwtVerifier:
    s = settings()
    return JwtVerifier(s.issuer, s.resource(mount), lambda token: _keys().key(token))


class Protected:
    """One mount behind the SDK's resource-server middleware (pure ASGI: the MCP streams are not buffered).

    BearerAuthBackend validates the token (and that it was issued for this mount's resource), RequireAuthMiddleware
    answers 401 (no/invalid/expired/wrong-audience/wrong-issuer token) or 403 insufficient_scope, both with
    `resource_metadata`. The challenge also names the mount's `scope` (MCP "Scope Selection Strategy", SHOULD), and a
    request without credentials gets no error code (RFC 6750 §3.1). The Host/Origin checks of the MCP transport run
    after this, as before E13-3."""

    def __init__(self, app: Any, mount: str) -> None:
        self.app, self.mount = app, mount

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        s = settings()
        backend = BearerAuthBackend(verifier(self.mount), resource_server_url=AnyHttpUrl(s.resource(self.mount)))
        result = await backend.authenticate(HTTPConnection(scope))
        scope = dict(scope)
        if result is not None:
            scope["auth"], scope["user"] = result
        has_credentials = any(k == b"authorization" for k, _v in scope.get("headers", []))
        guard = RequireAuthMiddleware(self.app, [SCOPES[self.mount]],
                                      AnyHttpUrl(s.metadata_url(self.mount)) if s.issuer else None)
        await guard(scope, receive, self._challenge(send, has_credentials))

    def _challenge(self, send: Any, has_credentials: bool) -> Any:
        scope_param = f'scope="{SCOPES[self.mount]}"'

        async def wrapped(message: dict) -> None:
            if message["type"] == "http.response.start" and message["status"] in (401, 403):
                headers = []
                for k, v in message.get("headers", []):
                    if k == b"www-authenticate":
                        value = v.decode()
                        if message["status"] == 401 and not has_credentials:
                            # RFC 6750 §3.1: no error code when the request carried no credentials
                            parts = [p for p in value.removeprefix("Bearer ").split(", ")
                                     if not p.startswith(("error=", "error_description="))]
                            value = "Bearer " + ", ".join(parts) if parts else "Bearer"
                        v = (value + (", " if value != "Bearer" else " ") + scope_param).encode()
                    headers.append((k, v))
                message = {**message, "headers": headers}
            await send(message)
        return wrapped


def metadata_routes() -> list[Route]:
    """RFC 9728 protected-resource metadata per mount (SDK helper), served at the root as the RFC requires:
    /.well-known/oauth-protected-resource/<mount>/mcp. Public: names the resource, its authorization server and its
    one scope; no patient data, no secret. None without an issuer (nothing to advertise; every mount answers 401)."""
    s = settings()
    if not s.issuer:
        return []
    routes: list[Route] = []
    for mount, scope in SCOPES.items():
        # plain strings: the SDK's metadata model keeps an empty path, so the issuer is advertised exactly (no
        # trailing slash added), as the client's RFC 8414 §3.3 issuer comparison is a simple string comparison
        routes += create_protected_resource_routes(resource_url=s.resource(mount),  # type: ignore[arg-type]
                                                   authorization_servers=[s.issuer],  # type: ignore[list-item]
                                                   scopes_supported=[scope], resource_name=NAMES[mount])
    return routes
