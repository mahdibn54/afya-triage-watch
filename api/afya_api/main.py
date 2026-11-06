"""Afya API (FastAPI). Endpoints follow docs/api.md. Routers live in routes_*.py; add new ones with one
`app.include_router(...)` line below."""
from fastapi import FastAPI

from . import routes_proposals, routes_vitals
from .errors import install_error_handlers

app = FastAPI(title="Afya Triage Watch API", version="0.1.0")
install_error_handlers(app)


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok"}


app.include_router(routes_vitals.router)       # E6-1b (M)
app.include_router(routes_proposals.router)    # E6-1b (M)
