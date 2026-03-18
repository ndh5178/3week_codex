"""별도 프로세스로 실행하는 Mini Redis 서버."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.redis_routes import router as redis_router
from app.services.redis_service import save_values


@asynccontextmanager
async def lifespan(_: FastAPI):
    """서버 종료 직전에 현재 메모리 상태를 dump 파일에 저장한다."""
    try:
        yield
    finally:
        save_values()


app = FastAPI(title="Mini Redis Server", lifespan=lifespan)
app.include_router(redis_router)
