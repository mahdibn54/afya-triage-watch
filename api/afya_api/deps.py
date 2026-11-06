"""FastAPI dependencies shared by the routers."""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Literal

import psycopg
from afya_mcp import db
from fastapi import HTTPException
from pydantic import BaseModel

from .mcp_client import Gateway, McpGateway

Role = Literal["nurse", "clinician", "manager"]


class User(BaseModel):
    id: str
    name: str
    role: Role


def current_user() -> User:
    """The signed-in user: ALWAYS from the session cookie, never from a request body.

    Implemented by E6-2 (B). Until then this raises 501, and tests replace it with
    `app.dependency_overrides[deps.current_user] = lambda: deps.User(id="nurse-a", name="Nurse A.", role="nurse")`.
    E6-2 replaces the body of this function (same name, same module, returns `User`; raise 401 when there is no
    session) or sets `app.dependency_overrides[current_user]` at startup. The routers only ever do
    `user: User = Depends(current_user)`; they use `user.id` as the audit actor and `user.role` for 403 checks.
    The users table is the source of truth for the role (workflow.py re-checks it in SQL anyway).
    """
    raise HTTPException(status_code=501, detail="demo session not available yet (E6-2)")


def get_conn() -> Iterator[psycopg.Connection]:
    """One autocommit afya_app connection per request (routes that use it are plain `def`, run in a thread)."""
    with db.connect() as conn:
        yield conn


_gateway: Gateway | None = None


def get_gateway() -> Gateway:
    """Client for afya-mcp (/act/mcp and /ui/mcp). Tests override this with an in-process fake."""
    global _gateway
    if _gateway is None:
        _gateway = McpGateway()
    return _gateway


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE") == "1"
