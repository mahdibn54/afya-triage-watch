"""FastAPI dependencies shared by the routers."""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import TYPE_CHECKING, Literal

import psycopg
from afya_mcp import db
from fastapi import Cookie, HTTPException
from psycopg.rows import DictRow
from pydantic import BaseModel

from . import session
from .mcp_client import Gateway, McpGateway
from .model import Model, model_from_env

if TYPE_CHECKING:
    from .agent import Agent

Role = Literal["nurse", "clinician", "manager"]


class User(BaseModel):
    id: str
    name: str
    role: Role


def current_user(afya_session: str | None = Cookie(default=None)) -> User:
    """The signed-in user: ALWAYS from the session cookie, never from a request body (E6-2, session.py).

    401 when demo mode is off (there is no other sign-in), or the cookie is missing, tampered with or expired, or
    the user is no longer a nurse, clinician or manager in afya.users. The role comes from afya.users on every
    request, never from the cookie. Tests replace this with
    `app.dependency_overrides[deps.current_user] = lambda: deps.User(id="nurse-a", name="Nurse A.", role="nurse")`.
    The routers only ever do `user: User = Depends(current_user)`; they use `user.id` as the audit actor and
    `user.role` for 403 checks (workflow.py re-checks the role in SQL anyway).
    """
    if not demo_mode():
        raise HTTPException(status_code=401, detail="sign in first: demo sign-in is off (DEMO_MODE=0)")
    try:
        uid = session.user_id_from(afya_session)
    except session.SessionUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from None
    row = session.load_user(uid) if uid else None
    if row is None:
        raise HTTPException(status_code=401, detail="sign in first")
    return User(**row)


def get_conn() -> Iterator[psycopg.Connection[DictRow]]:
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


_model: Model | None = None


def get_model() -> Model:
    """The guarded language model (E5-9), one per process so the circuit breaker is shared by all runs."""
    global _model
    if _model is None:
        _model = model_from_env()
    return _model


_agent: Agent | None = None


def get_agent() -> Agent:
    """The LangGraph agent (E5): starts a run after each saved reading and resumes it after approval. Tests override
    this with an agent on a scripted model."""
    global _agent
    if _agent is None:
        from .agent import Agent
        _agent = Agent(get_gateway(), get_model())
    return _agent


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE") == "1"
