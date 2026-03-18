"""FastAPI app entrypoint for the Mini Redis demo board."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.redis_routes import router as redis_router
from app.api.routes import router as api_router


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"

app = FastAPI(title="Mini Redis Board")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(api_router)
app.include_router(redis_router)


@app.get("/")
def read_index() -> FileResponse:
    """Serve the demo page."""
    return FileResponse(TEMPLATES_DIR / "index.html")
