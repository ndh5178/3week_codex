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
    """게시글 생성과 수정에 공통으로 쓰는 입력 형식이다."""

    title: str
    content: str
    author: str


class LoginPayload(BaseModel):
    """로그인 요청에서 받는 사용자 이름이다."""

    username: str


class LogoutPayload(BaseModel):
    """로그아웃 요청에서 받는 세션 정보다.

    token만 보내도 되고, 필요하면 완전한 session_key를 보낼 수도 있다.
    """

    token: str | None = None
    session_key: str | None = None


class SessionCheckPayload(BaseModel):
    """새로고침 뒤 로그인 복구를 위해 보내는 세션 토큰이다."""

    token: str


@router.get("/health")
def health_check() -> dict[str, str]:
    """서버가 켜져 있는지 확인한다."""
    return {"status": "ok"}


@router.get("/storage")
def read_storage_summary() -> dict[str, Any]:
    """현재 영속 저장소와 캐시 저장 방식을 반환한다."""
    return get_storage_summary()


@router.get("/posts")
def read_posts() -> dict[str, Any]:
    """전체 게시글 목록과 캐시/DB 출처 통계를 반환한다."""
    return list_posts()


@router.get("/posts/{post_id}")
def read_post(post_id: int) -> dict[str, Any]:
    """게시글 한 개를 반환한다."""
    post = get_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.get("/top-posts")
def read_top_posts() -> dict[str, Any]:
    """상위 인기글 목록을 반환한다."""
    return get_top_posts()


@router.post("/login")
def login_route(payload: LoginPayload) -> dict[str, Any]:
    """간단한 로그인 세션을 만든다."""
    try:
        return login(payload.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/logout")
def logout_route(payload: LogoutPayload) -> dict[str, Any]:
    """세션 토큰이나 세션 키를 받아 로그아웃 처리한다."""
    try:
        return logout(token=payload.token, session_key=payload.session_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/session/check")
def session_check_route(payload: SessionCheckPayload) -> dict[str, Any]:
    """토큰이 아직 유효한지 확인한다."""
    return check_session(payload.token)


@router.post("/posts")
def create_post_route(payload: PostPayload) -> dict[str, Any]:
    """새 게시글을 만든다."""
    create_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    return create_post(create_data)


@router.put("/posts/{post_id}")
def update_post_route(post_id: int, payload: PostPayload) -> dict[str, Any]:
    """게시글을 수정한다."""
    update_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    post = update_post(post_id, update_data)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("/posts/{post_id}/view")
def view_post_route(post_id: int) -> dict[str, Any]:
    """게시글을 열면서 조회수를 1 증가시킨다."""
    post = view_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("/posts/{post_id}/cache/clear")
def clear_post_cache_route(post_id: int) -> dict[str, Any]:
    """선택 게시글 캐시와 인기글 캐시를 비운다."""
    post = get_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return clear_post_cache(post_id)


@router.post("/posts/{post_id}/benchmark")
def benchmark_post_route(
    post_id: int,
    iterations: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    """선택 게시글의 DB 접근과 캐시 접근 속도를 비교한다."""
    benchmark = benchmark_post_access(post_id, iterations=iterations)
    if benchmark is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return benchmark
