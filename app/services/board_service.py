from __future__ import annotations

from datetime import datetime, UTC
import statistics
import secrets
import time
from typing import Any

from app.core.config import get_settings
from app.repositories.posts import get_posts_repository
from redis_engine.mini_redis import get_shared_redis


settings = get_settings()
posts_repository = get_posts_repository()
redis = get_shared_redis(data_file=settings.redis_dump_file)

TOP_POSTS_CACHE_KEY = "cache:top_posts"
SESSION_PREFIX = "session:"
POST_PREFIX = "post:"
POST_VIEWS_PREFIX = "views:post:"
SESSION_TTL_SECONDS = 1800
TOP_POSTS_TTL_SECONDS = 120


def get_storage_summary() -> dict[str, Any]:
    posts_path: str | None = None
    posts_storage = "disk"
    posts_label = "Unknown backend"

    if settings.posts_backend == "sqlite":
        posts_label = "SQLite on local disk"
        posts_path = str(settings.posts_sqlite_path)
    elif settings.posts_backend == "json":
        posts_label = "JSON file on local disk"
        posts_path = str(settings.posts_json_path)
    elif settings.posts_backend == "postgres":
        posts_label = "PostgreSQL server"
        posts_storage = "server"

    return {
        "posts": {
            "backend": settings.posts_backend,
            "label": posts_label,
            "storage": posts_storage,
            "path": posts_path,
        },
        "cache": {
            "backend": "mini-redis",
            "label": "Mini Redis in memory",
            "storage": "memory",
            "persistence_enabled": settings.redis_dump_file is not None,
            "persistence_path": (
                str(settings.redis_dump_file) if settings.redis_dump_file is not None else None
            ),
        },
    }


def list_posts() -> dict[str, Any]:
    posts: list[dict[str, Any]] = []
    cache_hits = 0
    db_hits = 0

    for raw_post in posts_repository.list_posts():
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

    redis.setex(TOP_POSTS_CACHE_KEY, TOP_POSTS_TTL_SECONDS, ranked_posts)
    return {
        "posts": ranked_posts,
        "count": len(ranked_posts),
        "source": "db",
        "ranking_rule": "views desc, id asc",
        "sources": posts_payload["sources"],
    }


def login(username: str) -> dict[str, Any]:
    clean_username = username.strip()
    if not clean_username:
        raise ValueError("Username is required")

    token = secrets.token_hex(8)
    session_key = _build_session_key(token)
    session_payload = {
        "username": clean_username,
        "token": token,
    }

    redis.setex(session_key, SESSION_TTL_SECONDS, session_payload)
    return {
        **session_payload,
        "session_key": session_key,
        "ttl_seconds": SESSION_TTL_SECONDS,
        "source": "redis",
    }


def check_session(token: str) -> dict[str, Any]:
    normalized_token = token.strip()
    if not normalized_token:
        return {
            "authenticated": False,
            "token": "",
            "username": None,
            "session_key": None,
            "message": "확인할 토큰이 없습니다.",
        }

    session_key = _build_session_key(normalized_token)
    session_payload = redis.get(session_key)
    if not isinstance(session_payload, dict):
        return {
            "authenticated": False,
            "token": normalized_token,
            "username": None,
            "session_key": session_key,
            "message": "세션이 없거나 이미 만료되었습니다.",
        }

    username = str(session_payload.get("username", "")).strip()
    if not username:
        return {
            "authenticated": False,
            "token": normalized_token,
            "username": None,
            "session_key": session_key,
            "message": "세션 데이터가 올바르지 않습니다.",
        }

    return {
        "authenticated": True,
        "token": normalized_token,
        "username": username,
        "session_key": session_key,
        "message": "유효한 로그인 세션입니다.",
    }


def logout(
    token: str | None = None,
    session_key: str | None = None,
) -> dict[str, Any]:
    resolved_session_key = _resolve_session_key(token=token, session_key=session_key)
    if resolved_session_key is None:
        raise ValueError("Token or session_key is required")

    stored_session = redis.get(resolved_session_key)
    deleted = redis.delete(resolved_session_key)
    resolved_token = token or _extract_token_from_session_key(resolved_session_key)
    username = stored_session.get("username") if isinstance(stored_session, dict) else None

    return {
        "token": resolved_token,
        "session_key": resolved_session_key,
        "username": username,
        "deleted": deleted,
    }


def get_post(post_id: int) -> dict[str, Any] | None:
    post, source = _get_cached_or_db_post(post_id)
    if post is None:
        return None
    return _serialize_post(post, source)


def create_post(payload: dict[str, Any]) -> dict[str, Any]:
    new_post = posts_repository.create_post(payload)
    new_post_id = int(new_post["id"])

    redis.delete(TOP_POSTS_CACHE_KEY)
    redis.delete(_build_post_cache_key(new_post_id))

    return {
        **_serialize_post(new_post, "db"),
        "created": True,
    }


def update_post(post_id: int, updates: dict[str, Any]) -> dict[str, Any] | None:
    updated_post = posts_repository.update_post(post_id, updates)
    if updated_post is None:
        return None

    cache_invalidated = redis.delete(_build_post_cache_key(post_id))
    top_posts_invalidated = redis.delete(TOP_POSTS_CACHE_KEY)
    return {
        **_serialize_post(updated_post, "db"),
        "cache_invalidated": cache_invalidated,
        "top_posts_invalidated": top_posts_invalidated,
    }


def view_post(post_id: int) -> dict[str, Any] | None:
    post = _load_post_from_db(post_id)
    if post is None:
        return None

    updated_views = redis.incr(_build_post_views_key(post_id))
    top_posts_invalidated = redis.delete(TOP_POSTS_CACHE_KEY)
    cached_post, source = _get_cached_or_db_post(post_id, fallback_post=post)
    if cached_post is None:
        return None

    return {
        **_serialize_post(cached_post, source),
        "views": updated_views,
        "top_posts_invalidated": top_posts_invalidated,
    }


def reset_cache() -> None:
    redis.clear()


def clear_post_cache(post_id: int) -> dict[str, Any]:
    deleted_post_cache = redis.delete(_build_post_cache_key(post_id))
    deleted_top_posts_cache = redis.delete(TOP_POSTS_CACHE_KEY)
    return {
        "post_id": post_id,
        "post_cache_deleted": deleted_post_cache,
        "top_posts_cache_deleted": deleted_top_posts_cache,
    }


def reset_posts_store() -> None:
    posts_repository.reset()


def count_posts() -> int:
    return posts_repository.count()


def benchmark_post_access(post_id: int, iterations: int = 20) -> dict[str, Any] | None:
    if iterations <= 0:
        raise ValueError("iterations must be greater than zero")

    base_post = _load_post_from_db(post_id)
    if base_post is None:
        return None

    db_timings_ms: list[float] = []
    cache_timings_ms: list[float] = []
    last_db_post: dict[str, Any] | None = None
    last_cache_post: dict[str, Any] | None = None
    cache_key = _build_post_cache_key(post_id)

    for _ in range(iterations):
        started = time.perf_counter()
        measured_post = _load_post_from_db(post_id)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if measured_post is None:
            return None
        db_timings_ms.append(elapsed_ms)
        last_db_post = measured_post

    redis.delete(cache_key)
    redis.set(cache_key, base_post)

    for _ in range(iterations):
        started = time.perf_counter()
        measured_post = redis.get(cache_key)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if not isinstance(measured_post, dict):
            return None
        cache_timings_ms.append(elapsed_ms)
        last_cache_post = measured_post

    storage_summary = get_storage_summary()
    database_label = storage_summary["posts"]["label"]
    cache_label = storage_summary["cache"]["label"]

    return {
        "post_id": post_id,
        "title": str((last_db_post or base_post).get("title", "")),
        "iterations": iterations,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "comparison": {
            "database_label": database_label,
            "cache_label": cache_label,
            "focus": "persistent read vs in-memory cache hit",
        },
        "storage": storage_summary,
        "db": {
            **_summarize_timings(db_timings_ms),
            "source": settings.posts_backend,
            "operation": "persistent read",
        },
        "cache": {
            **_summarize_timings(cache_timings_ms),
            "source": "mini-redis",
            "operation": "cache hit",
        },
        "speedup": round(
            _calculate_speedup(
                db_average_ms=statistics.mean(db_timings_ms),
                cache_average_ms=statistics.mean(cache_timings_ms),
            ),
            2,
        ),
    }


def _get_cached_or_db_post(
    post_id: int,
    fallback_post: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    cache_key = _build_post_cache_key(post_id)
    cached_post = redis.get(cache_key)
    if isinstance(cached_post, dict):
        return cached_post, "cache"

    post = fallback_post or _load_post_from_db(post_id)
    if post is None:
        return None, "db"

    redis.set(cache_key, post)
    return post, "db"


def _serialize_post(post: dict[str, Any], source: str) -> dict[str, Any]:
    post_id = int(post["id"])
    return {
        "id": post_id,
        "title": str(post.get("title", "")),
        "content": str(post.get("content", "")),
        "author": str(post.get("author", "")),
        "views": _get_post_views(post_id),
        "source": source,
    }


def _build_post_cache_key(post_id: int) -> str:
    return f"{POST_PREFIX}{post_id}"


def _build_post_views_key(post_id: int) -> str:
    return f"{POST_VIEWS_PREFIX}{post_id}"


def _build_session_key(token: str) -> str:
    return f"{SESSION_PREFIX}{token}"


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
    prefix = SESSION_PREFIX
    if session_key.startswith(prefix):
        return session_key[len(prefix):]
    return session_key


def _get_post_views(post_id: int) -> int:
    raw_views = redis.get(_build_post_views_key(post_id))
    try:
        return int(raw_views)
    except (TypeError, ValueError):
        return 0


def _load_post_from_db(post_id: int) -> dict[str, Any] | None:
    return posts_repository.get_post(post_id)


def _summarize_timings(timings_ms: list[float]) -> dict[str, float]:
    return {
        "average_ms": round(statistics.mean(timings_ms), 4),
        "median_ms": round(statistics.median(timings_ms), 4),
        "min_ms": round(min(timings_ms), 4),
        "max_ms": round(max(timings_ms), 4),
    }


def _calculate_speedup(db_average_ms: float, cache_average_ms: float) -> float:
    if cache_average_ms <= 0:
        return float("inf")
    return db_average_ms / cache_average_ms
