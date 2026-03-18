from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.board_service import (
    benchmark_post_access,
    check_session,
    clear_post_cache,
    create_post,
    get_post,
    get_storage_summary,
    get_top_posts,
    list_posts,
    login,
    logout,
    update_post,
    view_post,
)


router = APIRouter(tags=["posts"])


class PostPayload(BaseModel):
    title: str
    content: str
    author: str


class LoginPayload(BaseModel):
    username: str


class LogoutPayload(BaseModel):
    token: str | None = None
    session_key: str | None = None


class SessionCheckPayload(BaseModel):
    token: str


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/storage")
def read_storage_summary() -> dict[str, Any]:
    return get_storage_summary()


@router.get("/posts")
def read_posts() -> dict[str, Any]:
    return list_posts()


@router.get("/posts/{post_id}")
def read_post(post_id: int) -> dict[str, Any]:
    post = get_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.get("/top-posts")
def read_top_posts() -> dict[str, Any]:
    return get_top_posts()


@router.post("/login")
def login_route(payload: LoginPayload) -> dict[str, Any]:
    try:
        return login(payload.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/logout")
def logout_route(payload: LogoutPayload) -> dict[str, Any]:
    try:
        return logout(token=payload.token, session_key=payload.session_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/session/check")
def session_check_route(payload: SessionCheckPayload) -> dict[str, Any]:
    return check_session(payload.token)


@router.post("/posts")
def create_post_route(payload: PostPayload) -> dict[str, Any]:
    create_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    return create_post(create_data)


@router.put("/posts/{post_id}")
def update_post_route(post_id: int, payload: PostPayload) -> dict[str, Any]:
    update_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    post = update_post(post_id, update_data)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("/posts/{post_id}/view")
def view_post_route(post_id: int) -> dict[str, Any]:
    post = view_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("/posts/{post_id}/cache/clear")
def clear_post_cache_route(post_id: int) -> dict[str, Any]:
    post = get_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return clear_post_cache(post_id)


@router.post("/posts/{post_id}/benchmark")
def benchmark_post_route(
    post_id: int,
    iterations: int = Query(20, ge=1, le=200),
    mode: str = Query("both"),
) -> dict[str, Any]:
    try:
        benchmark = benchmark_post_access(post_id, iterations=iterations, mode=mode)
        if benchmark is None:
            raise HTTPException(status_code=404, detail="Post not found")
        return benchmark
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
