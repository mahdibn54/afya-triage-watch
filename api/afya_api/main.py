"""Afya API (FastAPI). Endpoints follow docs/api.md. Routers live in routes_*.py; add new ones with one
`app.include_router(...)` line below."""
import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from . import routes_demo, routes_proposals, routes_read, routes_session, routes_ui, routes_vitals, steps
from .deps import demo_mode, get_agent, get_gateway, get_model
from .errors import ApiError, install_error_handlers
from .executor import sweep_on_startup
from .watch import watch_loop


async def resume_unfinished(agent) -> list[dict]:
    return await agent.resume_unfinished()


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = [
        asyncio.create_task(sweep_on_startup(get_gateway(), agent=get_agent())),   # E6-4: resume approved commands
        asyncio.create_task(resume_unfinished(get_agent())),     # E12-1 S1: resume runs that stopped half-way
        asyncio.create_task(get_model().warm_up()),        # E5-9: warm-up call at start (never blocks startup)
        asyncio.create_task(watch_loop(get_gateway())),    # E5-7: reminders every WATCH_INTERVAL_SECONDS
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


# E12-3: /docs and /openapi.json only when DEMO_MODE=1 (checked per request; 404 otherwise). The UI's types are
# generated from /openapi.json in demo mode (docs/api.md section 1).
app = FastAPI(title="Afya Triage Watch API", version="0.1.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
install_error_handlers(app)


@app.get("/openapi.json", include_in_schema=False)
def openapi() -> JSONResponse:
    if not demo_mode():
        raise ApiError(404, "not found")
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
def docs() -> HTMLResponse:
    if not demo_mode():
        raise ApiError(404, "not found")
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - docs")


@app.get("/healthz")
def health() -> dict:
    """Liveness plus readiness of the language model (E12-1 S3): `model.ready` is true when the model may be called,
    its breaker is closed and the last call (or the warm-up) worked. The api is up either way: without the model it
    runs on the fixed rules. `trace_gaps`: agent_step rows that could not be written since start."""
    return {"status": "ok", "model": get_model().status(), "trace_gaps": steps.GAPS}


app.include_router(routes_vitals.router)       # E6-1b (M)
app.include_router(routes_proposals.router)    # E6-1b (M)
app.include_router(routes_ui.router)           # E6-5 (M)
app.include_router(routes_demo.router)         # E6-6 (M)
app.include_router(routes_session.demo)        # E6-2 (B): /login-as, /demo/users (DEMO_MODE only)
app.include_router(routes_session.router)      # E6-1a (B): /me
app.include_router(routes_read.router)         # E6-1a (B): /queue, /audit
