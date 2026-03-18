
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from redis_engine.mini_redis import get_shared_redis


BASE_DIR = Path(__file__).resolve().parents[2]
POSTS_FILE = BASE_DIR / "data" / "posts.json"
REDIS_DUMP_FILE = BASE_DIR / "data" / "redis_dump.json"
redis = get_shared_redis(data_file=REDIS_DUMP_FILE)


def get_post(post_id: int) -> dict[str, Any] | None:
    """Return a post from cache first, then fall back to the fake DB."""
    cache_key = _build_post_cache_key(post_id)
    cached_post = redis.get(cache_key)
    if isinstance(cached_post, dict):
        return {**cached_post, "source": "cache"}

    post = _load_post_from_fake_db(post_id)
    if post is None:
        return None

    redis.set(cache_key, post)
    return {**post, "source": "db"}


def update_post(post_id: int, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Update the fake DB record and invalidate any cached copy."""
    posts = _load_posts()
    updated_post: dict[str, Any] | None = None

    for post in posts:
        if post["id"] != post_id:
            continue

        updated_post = {
            "id": post_id,
            "title": str(updates.get("title", post["title"])),
            "content": str(updates.get("content", post["content"])),
            "author": str(updates.get("author", post["author"])),
        }
        post.update(updated_post)
        break

    if updated_post is None:
        return None

    _save_posts(posts)
    cache_invalidated = redis.delete(_build_post_cache_key(post_id))
    return {
        **updated_post,
        "source": "db",
        "cache_invalidated": cache_invalidated,
    }


def reset_cache() -> None:
    """Clear cached values between local runs or tests."""
    redis.clear()


def _build_post_cache_key(post_id: int) -> str:
    return f"post:{post_id}"


def _load_post_from_fake_db(post_id: int) -> dict[str, Any] | None:
    for post in _load_posts():
        if post["id"] == post_id:
            return post
    return None


def _load_posts() -> list[dict[str, Any]]:
    if not POSTS_FILE.exists():
        return []

    try:
        payload = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    raw_posts = payload.get("posts", [])
    if not isinstance(raw_posts, list):
        return []

    posts: list[dict[str, Any]] = []
    for raw_post in raw_posts:
        if not isinstance(raw_post, dict):
            continue

        try:
            post_id = int(raw_post["id"])
        except (KeyError, TypeError, ValueError):
            continue

        posts.append(
            {
                "id": post_id,
                "title": str(raw_post.get("title", "")),
                "content": str(raw_post.get("content", "")),
                "author": str(raw_post.get("author", "")),
            }
        )

    return posts


def _save_posts(posts: list[dict[str, Any]]) -> None:
    payload = {"posts": posts}
    POSTS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
