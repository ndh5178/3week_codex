"""FastAPI 라우트 모음이다.

이 파일은 URL 요청을 어떤 서비스 함수로 보낼지 정한다.
실제 데이터 처리 로직은 board_service.py가 맡고,
routes.py는 입구 역할만 하도록 분리해 둔 상태다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.board_service import (
    check_session,
    create_post,
    generate_demo_posts,
    get_post,
    get_top_posts,
    list_posts,
    login,
    logout,
    measure_view_increment_speed,
    randomize_post_views,
    reset_demo_database,
    update_post,
    view_post,
)


router = APIRouter(tags=["posts"])


class PostPayload(BaseModel):
    """게시글 생성/수정에 공통으로 쓰는 요청 형식이다."""

    title: str
    content: str
    author: str


class LoginPayload(BaseModel):
    """로그인 요청에서 받는 사용자 이름 형식이다."""

    username: str


class LogoutPayload(BaseModel):
    """로그아웃 요청 형식이다."""

    token: str | None = None
    session_key: str | None = None


class SessionCheckPayload(BaseModel):
    """세션 유효성 확인 요청 형식이다."""

    token: str


class DemoCountPayload(BaseModel):
    """몇 개를 만들지 정하는 데모 요청 형식이다."""

    count: int = 100


class DemoViewsPayload(BaseModel):
    """무작위 조회수 최대값을 정하는 데모 요청 형식이다."""

    max_views: int = 1000


@router.get("/health")
def health_check() -> dict[str, str]:
    """서버가 살아 있는지 확인하는 가장 간단한 API다."""
    return {"status": "ok"}


@router.get("/posts")
def read_posts() -> dict[str, Any]:
    """전체 게시글 목록과 cache/db 통계를 반환한다."""
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
    """인기글 상위 목록을 반환한다."""
    return get_top_posts()


@router.post("/login")
def login_route(payload: LoginPayload) -> dict[str, Any]:
    """사용자 이름을 받아 세션을 만든다."""
    try:
        return login(payload.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/logout")
def logout_route(payload: LogoutPayload) -> dict[str, Any]:
    """세션을 삭제해 로그아웃 처리한다."""
    try:
        return logout(token=payload.token, session_key=payload.session_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/session/check")
def session_check_route(payload: SessionCheckPayload) -> dict[str, Any]:
    """토큰이 아직 살아 있는지 확인한다."""
    return check_session(payload.token)


@router.post("/posts")
def create_post_route(payload: PostPayload) -> dict[str, Any]:
    """새 게시글을 만든다."""
    create_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    return create_post(create_data)


@router.post("/demo/generate-posts")
def generate_demo_posts_route(payload: DemoCountPayload) -> dict[str, Any]:
    """더미 게시글 여러 개를 자동 생성한다."""
    return generate_demo_posts(payload.count)


@router.post("/demo/randomize-views")
def randomize_demo_views_route(payload: DemoViewsPayload) -> dict[str, Any]:
    """게시글 조회수에 무작위 값을 넣는다."""
    return randomize_post_views(payload.max_views)


@router.get("/demo/speed-test")
def speed_test_route() -> dict[str, Any]:
    """조회수 1 증가를 DB 방식과 Redis 방식으로 비교한다."""
    return measure_view_increment_speed()


@router.post("/demo/reset-db")
def reset_demo_database_route() -> dict[str, Any]:
    """시연용 DB와 Redis 상태를 초기값으로 되돌린다."""
    return reset_demo_database()


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
