from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.board_service import (
    get_post,
    get_top_posts,
    increment_post_views,
    list_posts,
    login_user,
    logout_user,
    update_post,
)


router = APIRouter(tags=["posts"])


class PostUpdatePayload(BaseModel):
    title: str
    content: str
    author: str


class LoginPayload(BaseModel):
    username: str


class LogoutPayload(BaseModel):
    token: str | None = None
    session_key: str | None = None


@router.get("/health")
def health_check() -> dict[str, str]:
    """Simple endpoint for checking whether the server is running."""
    return {"status": "ok"}


@router.get("/posts")
def read_posts() -> dict[str, Any]:
    """Return the full post list with cache/db flow information."""
    return list_posts()


@router.get("/top-posts")
def read_top_posts() -> dict[str, Any]:
    """Return the cached leaderboard for the current top posts."""
    return get_top_posts()


@router.post("/login")
def login_route(payload: LoginPayload) -> dict[str, Any]:
    """Create a simple session and store it in MiniRedis."""
    try:
        return login_user(payload.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/logout")
def logout_route(payload: LogoutPayload) -> dict[str, Any]:
    """Delete a session using a token or a full Redis key."""
    try:
        return logout_user(token=payload.token, session_key=payload.session_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/posts/{post_id}")
def read_post(post_id: int) -> dict[str, Any]:
    """Return one post, using MiniRedis as the cache layer."""
    post = get_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    return post


@router.put("/posts/{post_id}")
def update_post_route(post_id: int, payload: PostUpdatePayload) -> dict[str, Any]:
    """Update a post in the fake DB and invalidate cached values."""
    update_data = (
        payload.model_dump()
        if hasattr(payload, "model_dump")
        else payload.dict()
    )
    post = update_post(post_id, update_data)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    return post


@router.post("/posts/{post_id}/view")
def increment_post_view_route(post_id: int) -> dict[str, Any]:
    """Increase one post's view counter."""
    view_state = increment_post_views(post_id)
    if view_state is None:
        raise HTTPException(status_code=404, detail="Post not found")

    return view_state
