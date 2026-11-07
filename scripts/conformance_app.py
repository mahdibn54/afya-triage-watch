"""Local ASGI wrapper for running the official MCP conformance tool against afya-mcp (E13-4).

E13-3: afya-mcp is an OAuth 2.1 protected resource. For the protocol (non-authorization) scenarios the conformance
CLI cannot obtain or send an access token, so this wrapper acts as a throwaway, offline issuer: at start it makes a
fresh RSA key pair in memory, points the real server app at it (issuer https://conformance.invalid, nothing is
fetched over the network) and adds a short-lived token for the requested mount (its audience and scope only) to every
request that carries no Authorization header. The key and the tokens live in this process only, are never printed
or written, and are worthless anywhere else. AFYA_CONFORMANCE_AUTH=off sends requests through untouched (401 with
the real challenge), for the authorization scenarios. Auth itself is covered by mcp/tests/test_auth.py.
Run: PYTHONPATH=mcp uvicorn conformance_app:app --app-dir scripts --port 9100
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://conformance.invalid"
BASE = "http://localhost:9100"
os.environ["AFYA_AUTH_ISSUER"] = ISSUER
os.environ["AFYA_MCP_RESOURCE_BASE"] = BASE

# imported after the environment above: afya_mcp.auth reads it once
from afya_mcp import auth
from afya_mcp.server import app as _app

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _Keys:
    async def key(self, _token: str) -> Any:
        return _KEY.public_key()


auth._keys = lambda: _Keys()


def _token(mount: str) -> bytes:
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": "conformance", "client_id": "conformance", "aud": [f"{BASE}/{mount}/mcp"],
              "scope": auth.SCOPES[mount], "iat": now, "exp": now + 300, "jti": str(uuid.uuid4())}
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"typ": "at+jwt"}).encode()


async def app(scope: dict, receive: Any, send: Any) -> None:
    if scope["type"] == "http" and os.environ.get("AFYA_CONFORMANCE_AUTH", "inject") != "off":
        mount = scope["path"].strip("/").split("/")[0]
        has_auth = any(k == b"authorization" for k, _v in scope["headers"])
        if mount in auth.SCOPES and not has_auth:
            scope = {**scope, "headers": [*scope["headers"], (b"authorization", b"Bearer " + _token(mount))]}
    await _app(scope, receive, send)
