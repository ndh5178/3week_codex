
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.board_service import get_post, update_post


router = APIRouter(tags=["posts"])


class PostUpdatePayload(BaseModel):
    title: str
    content: str
    author: str


@router.get("/health")
def health_check() -> dict[str, str]:
    """Simple endpoint for checking whether the server is running."""
    return {"status": "ok"}


@router.get("/posts/{post_id}")
def read_post(post_id: int) -> dict[str, Any]:
    """Return a post, using Mini Redis as the cache layer."""
    post = get_post(post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    return post


@router.put("/posts/{post_id}")
def update_post_route(post_id: int, payload: PostUpdatePayload) -> dict[str, Any]:
    """Update a post in the fake DB and invalidate any cached value."""
    update_data = (
        payload.model_dump()
        if hasattr(payload, "model_dump")
        else payload.dict()
    )
    post = update_post(post_id, update_data)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    return post
