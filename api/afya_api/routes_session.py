"""E6-1a / E6-2: "Sign in as…" for the demo (POST /login-as, GET /demo/users) and GET /me (docs/api.md section 4).

DEMO_MODE=1 only: /login-as and /demo/users answer 404 otherwise, before anything else. Signing in writes one audit row
(kind "login", the person as actor, auth "demo_switcher"). The session itself is in session.py.
"""
from __future__ import annotations

from afya_mcp import workflow
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response

from . import session
from .deps import User, current_user, demo_mode, get_conn
from .errors import ERROR_RESPONSES, ApiError
from .schemas import LoginIn, MeOut, UserOut


def require_demo_mode() -> None:
    if not demo_mode():
        raise HTTPException(status_code=404, detail="not found")


router = APIRouter(tags=["session"])
demo = APIRouter(tags=["session"], dependencies=[Depends(require_demo_mode)])


@demo.post("/login-as", response_model=UserOut, responses=ERROR_RESPONSES)
def login_as(body: LoginIn, response: Response, conn=Depends(get_conn)) -> UserOut:
    """Sign in as one of the demo people. 404 for an unknown user, or agent/system (they never sign in)."""
    row = session.load_user(body.user_id)
    if row is None:
        raise ApiError(404, "unknown user")
    try:
        token = session.sign(row["id"])
    except session.SessionUnavailable as e:
        raise ApiError(503, str(e)) from None
    workflow._audit(conn, "login", row["id"], None, {"role": row["role"]})
    response.set_cookie(session.COOKIE, token, max_age=session.MAX_AGE_S, httponly=True, samesite="strict",
                        secure=session.cookie_secure(), path="/")
    return UserOut(**row)


@demo.get("/demo/users", response_model=list[UserOut], responses=ERROR_RESPONSES)
def list_demo_users() -> list[UserOut]:
    """The people the switcher offers: nurses, clinicians, managers (never agent or system)."""
    return [UserOut(**u) for u in session.demo_users()]


@router.get("/me", response_model=MeOut, responses=ERROR_RESPONSES)
def me(user: User = Depends(current_user)) -> MeOut:
    return MeOut(id=user.id, name=user.name, role=user.role, demo=demo_mode())


@router.post("/logout", status_code=204, response_class=Response, responses=ERROR_RESPONSES)
def logout(afya_session: str | None = Cookie(default=None), conn=Depends(get_conn)) -> Response:
    """Clear the demo session, including expired/invalid cookies. Audit a recognized signed-in person."""
    try:
        uid = session.user_id_from(afya_session)
    except session.SessionUnavailable:
        uid = None
    user = session.load_user(uid) if uid else None
    if user is not None:
        workflow._audit(conn, "logout", user["id"], None, {"role": user["role"]})
    response = Response(status_code=204)
    response.delete_cookie(session.COOKIE, path="/", secure=session.cookie_secure(), httponly=True, samesite="strict")
    return response
