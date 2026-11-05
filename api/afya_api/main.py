"""Afya API (FastAPI). Endpoints follow docs/api.md; bodies are filled in during E6."""
from fastapi import FastAPI

app = FastAPI(title="Afya Triage Watch API", version="0.1.0")


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok"}
