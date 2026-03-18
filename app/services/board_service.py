from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from redis_engine.mini_redis import get_shared_redis


BASE_DIR = Path(__file__).resolve().parents[2]
POSTS_FILE = BASE_DIR / "data" / "posts.json"
REDIS_DUMP_FILE = BASE_DIR / "data" / "redis_dump.json"
TOP_POSTS_CACHE_KEY = "top-posts"
redis = get_shared_redis(data_file=REDIS_DUMP_FILE)


def list_posts() -> dict[str, Any]:
    """Return every post and report how many items came from cache or DB."""
    posts: list[dict[str, Any]] = []
    cache_hits = 0
    db_hits = 0

    for raw_post in _load_posts():
        post, source = _get_cached_or_db_post(raw_post["id"], fallback_post=raw_post)
        if post is None:
            continue

        if source == "cache":
            cache_hits += 1
        else:
            db_hits += 1

        posts.append(_serialize_post(post, source))

    return {
        "posts": posts,
        "count": len(posts),
        "sources": {
            "cache": cache_hits,
            "db": db_hits,
        },
    }


def get_top_posts(limit: int = 3) -> dict[str, Any]:
    """Return a small leaderboard and cache the computed result."""
    cached_posts = redis.get(TOP_POSTS_CACHE_KEY)
    if isinstance(cached_posts, list):
        return {
            "posts": cached_posts[:limit],
            "count": min(len(cached_posts), limit),
            "source": "cache",
            "ranking_rule": "views desc, id asc",
        }

    posts_payload = list_posts()
    ranked_posts = sorted(
        posts_payload["posts"],
        key=lambda post: (-int(post.get("views", 0)), int(post.get("id", 0))),
    )[:limit]

    redis.set(TOP_POSTS_CACHE_KEY, ranked_posts)
    return {
        "posts": ranked_posts,
        "count": len(ranked_posts),
        "source": "computed",
        "ranking_rule": "views desc, id asc",
        "sources": posts_payload["sources"],
    }


def get_post(post_id: int) -> dict[str, Any] | None:
    """Return a post from cache first, then fall back to the fake DB."""
    post, source = _get_cached_or_db_post(post_id)
    if post is None:
        return None

    return _serialize_post(post, source)


def update_post(post_id: int, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Update the fake DB record and invalidate cached copies."""
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
    top_posts_cache_invalidated = redis.delete(TOP_POSTS_CACHE_KEY)
    return {
        **_serialize_post(updated_post, "db"),
        "cache_invalidated": cache_invalidated,
        "top_posts_cache_invalidated": top_posts_cache_invalidated,
    }


def login_user(username: str) -> dict[str, Any]:
    """Create a very small session object and store it in MiniRedis."""
    clean_username = username.strip()
    if not clean_username:
        raise ValueError("Username is required")

    token = uuid4().hex
    session_key = _build_session_key(token)
    session_payload = {
        "username": clean_username,
        "token": token,
    }
    redis.set(session_key, session_payload)
    return {
        **session_payload,
        "session_key": session_key,
        "source": "redis",
    }


def logout_user(
    token: str | None = None,
    session_key: str | None = None,
) -> dict[str, Any]:
    """Delete a saved session by token or by a full Redis key."""
    resolved_session_key = _resolve_session_key(token=token, session_key=session_key)
    if resolved_session_key is None:
        raise ValueError("Token or session_key is required")

    stored_session = redis.get(resolved_session_key)
    logged_out = redis.delete(resolved_session_key)
    resolved_token = token or _extract_token_from_session_key(resolved_session_key)
    username = stored_session.get("username") if isinstance(stored_session, dict) else None

    return {
        "token": resolved_token,
        "session_key": resolved_session_key,
        "username": username,
        "logged_out": logged_out,
    }


def increment_post_views(post_id: int) -> dict[str, Any] | None:
    """Increase the view counter for one post and clear top-posts cache."""
    if _load_post_from_fake_db(post_id) is None:
        return None

    views = redis.incr(_build_post_views_key(post_id))
    top_posts_cache_invalidated = redis.delete(TOP_POSTS_CACHE_KEY)
    return {
        "post_id": post_id,
        "views": views,
        "top_posts_cache_invalidated": top_posts_cache_invalidated,
    }


def reset_cache() -> None:
    """Clear cached values between local runs or tests."""
    redis.clear()


def _get_cached_or_db_post(
    post_id: int,
    fallback_post: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Read from MiniRedis first so the cache flow stays visible."""
    cache_key = _build_post_cache_key(post_id)
    cached_post = redis.get(cache_key)
    if isinstance(cached_post, dict):
        return cached_post, "cache"

    post = fallback_post or _load_post_from_fake_db(post_id)
    if post is None:
        return None, "db"

    # We cache only the main post body. Dynamic values like views stay separate.
    redis.set(cache_key, post)
    return post, "db"


def _serialize_post(post: dict[str, Any], source: str) -> dict[str, Any]:
    """Build one API-friendly post object."""
    post_id = int(post["id"])
    return {
        "id": post_id,
        "title": str(post.get("title", "")),
        "content": str(post.get("content", "")),
        "author": str(post.get("author", "")),
        "views": _get_post_views(post_id),
        "source": source,
    }


def _get_post_views(post_id: int) -> int:
    raw_views = redis.get(_build_post_views_key(post_id))
    try:
        return int(raw_views)
    except (TypeError, ValueError):
        return 0


def _build_post_cache_key(post_id: int) -> str:
    return f"post:{post_id}"


def _build_post_views_key(post_id: int) -> str:
    return f"post:{post_id}:views"


def _build_session_key(token: str) -> str:
    return f"session:{token}"


def _resolve_session_key(
    token: str | None = None,
    session_key: str | None = None,
) -> str | None:
    if session_key:
        return str(session_key)
    if token:
        return _build_session_key(token)
    return None


def _extract_token_from_session_key(session_key: str) -> str:
    prefix = "session:"
    if session_key.startswith(prefix):
        return session_key[len(prefix):]
    return session_key


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
