"""Error body of docs/api.md section 1: always {"error": {"code", "message"[, "problems"]}}.

E12-3: Starlette's own 404/405 (unknown path, wrong method) get the same body, and any other exception (a database
outage, a bug) becomes a generic 503 with no details; the exception itself is logged server-side only."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("afya_api.errors")

CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid", 501: "unavailable",
         503: "unavailable"}


class ErrorDetail(BaseModel):
    code: str
    message: str
    problems: list[Any] | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail


class ApiError(Exception):
    def __init__(self, status: int, message: str, problems: list[Any] | None = None) -> None:
        super().__init__(message)
        self.status, self.message, self.problems = status, message, problems


def body(status: int, message: str, problems: list[Any] | None = None) -> JSONResponse:
    err: dict[str, Any] = {"code": CODES.get(status, "invalid" if status < 500 else "unavailable"), "message": message}
    if problems is not None:
        err["problems"] = problems
    return JSONResponse({"error": err}, status_code=status)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_r: Request, e: ApiError) -> JSONResponse:
        return body(e.status, e.message, e.problems)

    # FastAPI's HTTPException is a subclass: one handler covers our raises and Starlette's routing 404/405.
    @app.exception_handler(StarletteHTTPException)
    async def _http(_r: Request, e: StarletteHTTPException) -> JSONResponse:
        headers = getattr(e, "headers", None)
        resp = body(e.status_code, str(e.detail))
        if headers:
            resp.headers.update(headers)   # e.g. Allow on a 405
        return resp

    @app.exception_handler(Exception)
    async def _unexpected(r: Request, e: Exception) -> JSONResponse:
        log.error("unhandled %s on %s %s", type(e).__name__, r.method, r.url.path, exc_info=e)
        return body(503, "the service is unavailable; try again")

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, e: RequestValidationError) -> JSONResponse:
        problems = [{"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
                    for err in e.errors()]
        return body(422, "the request is not valid", problems)


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    c: {"model": ErrorBody} for c in (401, 403, 404, 409, 422, 503)}
