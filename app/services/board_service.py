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
POSTS_LIST_CACHE_KEY = "cache:posts:list"
SESSION_PREFIX = "session:"
POST_PREFIX = "post:"
POST_VIEWS_PREFIX = "views:post:"
SESSION_TTL_SECONDS = 1800
TOP_POSTS_TTL_SECONDS = 120
POSTS_LIST_TTL_SECONDS = 120


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
    raw_posts, list_source = _get_cached_or_db_posts_list()
    posts = [_serialize_post(raw_post, list_source) for raw_post in raw_posts]
    cache_hits = len(posts) if list_source == "cache" else 0
    db_hits = len(posts) if list_source == "db" else 0

    return {
        "posts": posts,
        "count": len(posts),
        "list_source": list_source,
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

    redis.delete(POSTS_LIST_CACHE_KEY)
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

    list_cache_invalidated = redis.delete(POSTS_LIST_CACHE_KEY)
    cache_invalidated = redis.delete(_build_post_cache_key(post_id))
    top_posts_invalidated = redis.delete(TOP_POSTS_CACHE_KEY)
    return {
        **_serialize_post(updated_post, "db"),
        "list_cache_invalidated": list_cache_invalidated,
        "cache_invalidated": cache_invalidated,
        "top_posts_invalidated": top_posts_invalidated,
    }


def view_post(post_id: int) -> dict[str, Any] | None:
    post, source = _get_cached_or_db_post(post_id)
    if post is None:
        return None

    updated_views = redis.incr(_build_post_views_key(post_id))
    top_posts_invalidated = redis.delete(TOP_POSTS_CACHE_KEY)

    return {
        **_serialize_post(post, source),
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


def benchmark_post_access(
    post_id: int,
    iterations: int = 20,
    mode: str = "both",
) -> dict[str, Any] | None:
    if iterations <= 0:
        raise ValueError("iterations must be greater than zero")

    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"both", "db", "cache"}:
        raise ValueError("mode must be one of: both, db, cache")

    base_post = _load_post_from_db(post_id)
    if base_post is None:
        return None

    storage_summary = get_storage_summary()
    database_label = f"{storage_summary['posts']['label']} direct read"
    cache_label = f"{storage_summary['cache']['label']} direct key lookup"
    db_summary: dict[str, Any] | None = None
    cache_summary: dict[str, Any] | None = None

    if normalized_mode in {"both", "db"}:
        db_timings_ms, last_db_post = _measure_direct_db_access(post_id, iterations)
        db_summary = {
            **_summarize_timings(db_timings_ms),
            "source": "disk" if storage_summary["posts"]["storage"] == "disk" else "server",
            "operation": "repository.get_post",
        }

    if normalized_mode == "both":
        redis.set(_build_post_cache_key(post_id), base_post)

    if normalized_mode in {"both", "cache"}:
        cache_timings_ms, last_cache_post = _measure_direct_cache_access(post_id, iterations)
        cache_summary = {
            **_summarize_timings(cache_timings_ms),
            "source": "memory",
            "operation": "redis.get(post_cache_key)",
        }

    return {
        "post_id": post_id,
        "title": str(base_post.get("title", "")),
        "iterations": iterations,
        "mode": normalized_mode,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "comparison": {
            "database_label": database_label,
            "cache_label": cache_label,
            "focus": "direct persistent-store read vs direct in-memory cache lookup",
        },
        "storage": storage_summary,
        "db": db_summary,
        "cache": cache_summary,
        "speedup": (
            round(
                _calculate_speedup(
                    db_average_ms=float(db_summary["average_ms"]),
                    cache_average_ms=float(cache_summary["average_ms"]),
                ),
                2,
            )
            if db_summary is not None and cache_summary is not None
            else None
        ),
    }


def _measure_direct_db_access(
    post_id: int,
    iterations: int,
) -> tuple[list[float], dict[str, Any]]:
    timings_ms: list[float] = []
    last_post: dict[str, Any] | None = None

    for _ in range(iterations):
        started = time.perf_counter()
        measured_post = _load_post_from_db(post_id)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if measured_post is None:
            raise ValueError("Post not found")
        timings_ms.append(elapsed_ms)
        last_post = measured_post

    if last_post is None:
        raise ValueError("Post not found")

    return timings_ms, last_post


def _measure_direct_cache_access(
    post_id: int,
    iterations: int,
) -> tuple[list[float], dict[str, Any]]:
    timings_ms: list[float] = []
    last_post: dict[str, Any] | None = None
    cache_key = _build_post_cache_key(post_id)

    cached_post = redis.get(cache_key)
    if not isinstance(cached_post, dict):
        raise ValueError("Post cache is empty")

    for _ in range(iterations):
        started = time.perf_counter()
        measured_post = redis.get(cache_key)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if not isinstance(measured_post, dict):
            raise ValueError("Post cache is empty")
        timings_ms.append(elapsed_ms)
        last_post = measured_post

    if last_post is None:
        raise ValueError("Post cache is empty")

    return timings_ms, last_post


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


def _get_cached_or_db_posts_list() -> tuple[list[dict[str, Any]], str]:
    cached_posts = redis.get(POSTS_LIST_CACHE_KEY)
    if isinstance(cached_posts, list):
        return [post for post in cached_posts if isinstance(post, dict)], "cache"

    posts = posts_repository.list_posts()
    redis.setex(POSTS_LIST_CACHE_KEY, POSTS_LIST_TTL_SECONDS, posts)
    return posts, "db"


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
    sorted_timings = sorted(timings_ms)
    return {
        "average_ms": round(statistics.mean(timings_ms), 4),
        "median_ms": round(statistics.median(timings_ms), 4),
        "min_ms": round(min(timings_ms), 4),
        "max_ms": round(max(timings_ms), 4),
        "p95_ms": round(_calculate_percentile(sorted_timings, 0.95), 4),
    }


def _calculate_speedup(db_average_ms: float, cache_average_ms: float) -> float:
    if cache_average_ms <= 0:
        return float("inf")
    return db_average_ms / cache_average_ms


def _calculate_percentile(sorted_timings: list[float], percentile: float) -> float:
    if not sorted_timings:
        return 0.0

    bounded_percentile = min(max(percentile, 0.0), 1.0)
    last_index = len(sorted_timings) - 1
    position = last_index * bounded_percentile
    lower_index = int(position)
    upper_index = min(lower_index + 1, last_index)
    weight = position - lower_index

    lower_value = sorted_timings[lower_index]
    upper_value = sorted_timings[upper_index]
    return lower_value + (upper_value - lower_value) * weight
