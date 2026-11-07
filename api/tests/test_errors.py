"""E12-3: every error has the body of docs/api.md section 1, and /docs, /openapi.json exist only in DEMO_MODE=1.
No database needed: the routes used here fail before touching it."""
from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from support import error

from afya_api import deps
from afya_api.main import app


def _client() -> TestClient:
    # raise_server_exceptions=False: see what a browser would get, not the exception re-raised by the test client
    return TestClient(app, raise_server_exceptions=False)


def test_starlette_404_and_405_have_the_error_body():
    c = _client()
    error(c.get("/no-such-path"), 404, "not_found")
    r = c.delete("/healthz")
    assert error(r, 405, "invalid") and "GET" in r.headers["allow"]


def test_an_unexpected_exception_is_a_generic_503_and_logged(monkeypatch, caplog):
    def boom() -> None:
        raise RuntimeError("connection to server at 10.0.0.5 failed: password authentication failed")

    app.dependency_overrides[deps.current_user] = boom
    try:
        with caplog.at_level(logging.ERROR, logger="afya_api.errors"):
            r = _client().get("/me")
    finally:
        app.dependency_overrides.clear()
    err = error(r, 503, "unavailable")
    assert "10.0.0.5" not in r.text and "password" not in r.text and "RuntimeError" not in r.text
    assert err["message"] == "the service is unavailable; try again"
    assert any("RuntimeError" in rec.getMessage() for rec in caplog.records)


def test_docs_and_openapi_only_in_demo_mode(monkeypatch):
    c = _client()
    monkeypatch.setenv("DEMO_MODE", "0")
    for path in ("/openapi.json", "/docs", "/redoc"):
        error(c.get(path), 404, "not_found")
    monkeypatch.setenv("DEMO_MODE", "1")
    assert c.get("/openapi.json").json()["info"]["title"] == "Afya Triage Watch API"
    assert c.get("/docs").status_code == 200
    assert "/openapi.json" not in c.get("/openapi.json").json()["paths"]   # the doc routes are not in the schema
