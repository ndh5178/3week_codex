"""FastAPI 앱의 시작점이다.

이 파일은 크게 3가지를 담당한다.
1. FastAPI 앱 객체 만들기
2. 정적 파일(CSS, JS) 연결하기
3. 브라우저가 처음 들어왔을 때 index.html 보여주기
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"

app = FastAPI(title="Mini Redis Board")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(api_router)


@app.get("/")
def read_index() -> FileResponse:
    """웹페이지 첫 화면(index.html)을 반환한다."""
    return FileResponse(TEMPLATES_DIR / "index.html")
