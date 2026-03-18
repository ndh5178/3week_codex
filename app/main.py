"""FastAPI 실행 진입점.

지금 단계에서는 복잡한 API보다 먼저
"웹 껍데기 + static 파일이 제대로 보이게 연결하는 것"이 목표다.

즉 이 파일이 하는 일:
1. FastAPI 앱 만들기
2. /static 경로에 CSS, JS 연결하기
3. / 요청 시 index.html 보여주기
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"

app = FastAPI(title="Mini Redis Board")

# CSS와 JS 파일을 /static/... 주소로 열 수 있게 연결한다.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def read_index() -> FileResponse:
    """메인 페이지(index.html)를 반환한다."""
    return FileResponse(TEMPLATES_DIR / "index.html")
