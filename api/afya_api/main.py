"""Afya API (FastAPI). Endpoints follow docs/api.md. Routers live in routes_*.py; add new ones with one
`app.include_router(...)` line below."""
import asyncio
import contextlib

from fastapi import FastAPI

from . import routes_demo, routes_proposals, routes_ui, routes_vitals
from .deps import get_gateway
from .errors import install_error_handlers
from .executor import sweep_on_startup


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(sweep_on_startup(get_gateway()))   # E6-4: resume approved commands that are not done
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Afya Triage Watch API", version="0.1.0", lifespan=lifespan)
install_error_handlers(app)


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok"}


app.include_router(routes_vitals.router)       # E6-1b (M)
app.include_router(routes_proposals.router)    # E6-1b (M)
app.include_router(routes_ui.router)           # E6-5 (M)
app.include_router(routes_demo.router)         # E6-6 (M)
