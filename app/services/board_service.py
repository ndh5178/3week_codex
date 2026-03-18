from __future__ import annotations

import random
import secrets
import statistics
import time
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument

from app.core.config import get_settings
from app.repositories.posts import get_posts_repository
from redis_engine.client import get_shared_redis_client


settings = get_settings()
posts_repository = get_posts_repository()
redis = get_shared_redis_client(
    backend=settings.mini_redis_backend,
    base_url=settings.mini_redis_url,
    timeout_seconds=settings.mini_redis_timeout_seconds,
    data_file=settings.redis_dump_file,
)

TOP_POSTS_CACHE_KEY = "cache:top_posts"
SESSION_PREFIX = "session:"
POST_PREFIX = "post:"
POST_VIEWS_PREFIX = "views:post:"
SESSION_TTL_SECONDS = 1800
POST_CACHE_TTL_SECONDS = 10
TOP_POSTS_TTL_SECONDS = 10


def get_storage_summary() -> dict[str, Any]:
    return {
        "posts": {
            "backend": "mongodb",
            "label": "MongoDB server",
            "storage": "server",
            "path": f"{settings.mongodb_uri}/{settings.mongodb_database}.{settings.mongodb_collection}",
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
    posts = [_serialize_post(raw_post, "db") for raw_post in posts_repository.list_posts()]
    return {
        "posts": posts,
        "count": len(posts),
        "sources": {
            "cache": 0,
            "db": len(posts),
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


def delete_post(post_id: int) -> dict[str, Any] | None:
    deleted_post = posts_repository.delete_post(post_id)
    if deleted_post is None:
        return None

    deleted_post_cache = redis.delete(_build_post_cache_key(post_id))
    deleted_post_views = redis.delete(_build_post_views_key(post_id))
    deleted_top_posts_cache = redis.delete(TOP_POSTS_CACHE_KEY)

    return {
        **_serialize_post(deleted_post, "db"),
        "deleted": True,
        "post_cache_deleted": deleted_post_cache,
        "views_cache_deleted": deleted_post_views,
        "top_posts_cache_deleted": deleted_top_posts_cache,
    }


def view_post(post_id: int) -> dict[str, Any] | None:
    post, source, access_metrics = _get_post_with_live_access_metrics(post_id)
    if post is None:
        return None

    updated_views = redis.incr(_build_post_views_key(post_id))
    top_posts_invalidated = redis.delete(TOP_POSTS_CACHE_KEY)
    return {
        **_serialize_post(post, source),
        "views": updated_views,
        "top_posts_invalidated": top_posts_invalidated,
        "live_access": access_metrics,
        "cache": get_post_cache_status(post_id),
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


def get_post_cache_status(post_id: int) -> dict[str, Any]:
    cache_key = _build_post_cache_key(post_id)
    ttl_seconds = redis.ttl(cache_key)
    exists = ttl_seconds != -2
    return {
        "post_id": post_id,
        "cache_key": cache_key,
        "exists": exists,
        "ttl_seconds": ttl_seconds if ttl_seconds >= 0 else None,
        "is_persistent": ttl_seconds == -1,
        "is_expired": ttl_seconds == -2,
    }


def reset_posts_store() -> None:
    posts_repository.reset()
    _reset_mongodb_view_counter_collection()


def count_posts() -> int:
    return posts_repository.count()


def generate_demo_posts(count: int = 100) -> dict[str, Any]:
    safe_count = max(1, count)
    topic_words = [
        "Redis 캐시",
        "조회수 카운터",
        "세션 저장",
        "인기글 계산",
        "FastAPI 라우팅",
        "메모리 저장소",
        "TTL 만료",
        "캐시 무효화",
    ]
    authors = ["동현", "지민", "민아", "준", "보라", "학생A", "학생B"]

    first_created_id: int | None = None
    last_created_id: int | None = None

    for index in range(safe_count):
        topic = topic_words[index % len(topic_words)]
        created_post = posts_repository.create_post(
            {
                "title": f"{topic} 데모 글 {index + 1}",
                "content": (
                    f"{topic}가 실제 서비스에서 어떻게 동작하는지 설명하는 자동 생성 게시글입니다. "
                    f"이 글은 데모용 데이터로 사용되며 번호는 {index + 1}번입니다."
                ),
                "author": authors[index % len(authors)],
            }
        )

        created_post_id = int(created_post["id"])
        if first_created_id is None:
            first_created_id = created_post_id
        last_created_id = created_post_id
        redis.delete(_build_post_cache_key(created_post_id))

    redis.delete(TOP_POSTS_CACHE_KEY)

    return {
        "created_count": safe_count,
        "total_posts": posts_repository.count(),
        "first_created_id": first_created_id,
        "last_created_id": last_created_id,
    }


def randomize_post_views(max_views: int = 1000) -> dict[str, Any]:
    safe_max_views = max(1, max_views)
    posts = posts_repository.list_posts()
    updated_views: list[int] = []

    for post in posts:
        randomized_views = random.randint(0, safe_max_views)
        redis.set(_build_post_views_key(int(post["id"])), randomized_views)
        updated_views.append(randomized_views)

    redis.delete(TOP_POSTS_CACHE_KEY)

    return {
        "updated_posts": len(posts),
        "max_views": max(updated_views, default=0),
        "min_views": min(updated_views, default=0),
    }


def measure_view_increment_speed(
    db_iterations: int = 30,
    redis_iterations: int = 300,
) -> dict[str, Any]:
    posts = posts_repository.list_posts()
    if not posts:
        return {
            "db_average_ms": 0.0,
            "redis_average_ms": 0.0,
            "db_iterations": 0,
            "redis_iterations": 0,
            "speed_ratio": None,
            "target_post_id": None,
            "comparison": "view_increment",
            "message": "비교할 게시글이 없어 속도를 측정할 수 없습니다.",
        }

    target_post_id = int(posts[0]["id"])
    safe_db_iterations = max(1, db_iterations)
    safe_redis_iterations = max(1, redis_iterations)
    redis_key = _build_post_views_key(target_post_id)
    original_redis_views = redis.get(redis_key)
    original_db_counter = _get_mongodb_view_counter(target_post_id)

    try:
        db_total_ms = 0.0
        for _ in range(safe_db_iterations):
            started_at = time.perf_counter()
            _increment_mongodb_view_counter(target_post_id)
            db_total_ms += (time.perf_counter() - started_at) * 1000

        redis.set(redis_key, 0)

        redis_total_ms = 0.0
        for _ in range(safe_redis_iterations):
            started_at = time.perf_counter()
            redis.incr(redis_key)
            redis_total_ms += (time.perf_counter() - started_at) * 1000

        db_average_ms = round(db_total_ms / safe_db_iterations, 3)
        redis_average_ms = round(redis_total_ms / safe_redis_iterations, 3)
        speed_ratio = round(db_average_ms / redis_average_ms, 2) if redis_average_ms > 0 else None

        return {
            "db_average_ms": db_average_ms,
            "redis_average_ms": redis_average_ms,
            "db_iterations": safe_db_iterations,
            "redis_iterations": safe_redis_iterations,
            "speed_ratio": speed_ratio,
            "target_post_id": target_post_id,
            "comparison": "view_increment",
            "message": "같은 게시글의 조회수 1 증가를 MongoDB 방식과 Redis INCR 방식으로 비교한 결과입니다.",
        }
    finally:
        _set_mongodb_view_counter(target_post_id, original_db_counter)
        if original_redis_views is None:
            redis.delete(redis_key)
        else:
            redis.set(redis_key, original_redis_views)


def reset_demo_database() -> dict[str, Any]:
    reset_posts_store()
    reset_cache()
    return {
        "reset": True,
        "post_count": posts_repository.count(),
        "message": "게시글 저장소와 Redis 캐시를 초기 상태로 되돌렸습니다.",
    }


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

    return {
        "post_id": post_id,
        "title": str((last_db_post or base_post).get("title", "")),
        "iterations": iterations,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "comparison": {
            "database_label": storage_summary["posts"]["label"],
            "cache_label": storage_summary["cache"]["label"],
            "focus": "persistent read vs in-memory cache hit",
        },
        "storage": storage_summary,
        "db": {
            **_summarize_timings(db_timings_ms),
            "source": "mongodb",
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

    redis.setex(cache_key, POST_CACHE_TTL_SECONDS, post)
    return post, "db"


def _get_post_with_live_access_metrics(
    post_id: int,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    cache_key = _build_post_cache_key(post_id)

    cache_started_at = time.perf_counter()
    cached_post = redis.get(cache_key)
    cache_read_ms = (time.perf_counter() - cache_started_at) * 1000

    if isinstance(cached_post, dict):
        return cached_post, "cache", {
            "source": "cache",
            "db_read_ms": None,
            "cache_read_ms": round(cache_read_ms, 3),
            "speedup": None,
            "cache_key": cache_key,
            "cache_ttl_seconds": _normalize_cache_ttl(redis.ttl(cache_key)),
        }

    db_started_at = time.perf_counter()
    db_post = _load_post_from_db(post_id)
    db_read_ms = (time.perf_counter() - db_started_at) * 1000
    if db_post is None:
        return None, "db", {
            "source": "db",
            "db_read_ms": round(db_read_ms, 3),
            "cache_read_ms": None,
            "speedup": None,
        }

    redis.setex(cache_key, POST_CACHE_TTL_SECONDS, db_post)
    return db_post, "db", {
        "source": "db",
        "db_read_ms": round(db_read_ms, 3),
        "cache_read_ms": None,
        "speedup": None,
        "cache_key": cache_key,
        "cache_ttl_seconds": _normalize_cache_ttl(redis.ttl(cache_key)),
    }


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
    if session_key.startswith(SESSION_PREFIX):
        return session_key[len(SESSION_PREFIX):]
    return session_key


def _get_post_views(post_id: int) -> int:
    raw_views = redis.get(_build_post_views_key(post_id))
    try:
        return int(raw_views)
    except (TypeError, ValueError):
        return 0


def _normalize_cache_ttl(ttl_seconds: int) -> int | None:
    if ttl_seconds < 0:
        return None
    return ttl_seconds


def _load_post_from_db(post_id: int) -> dict[str, Any] | None:
    return posts_repository.get_post(post_id)


def _get_mongodb_view_counter_collection():
    from pymongo import MongoClient

    client = MongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=settings.mongodb_connect_timeout_ms,
        connectTimeoutMS=settings.mongodb_connect_timeout_ms,
    )
    database = client[settings.mongodb_database]
    return database[f"{settings.mongodb_collection}_view_benchmark_counters"]


def _ensure_mongodb_view_counter_collection() -> None:
    _get_mongodb_view_counter_collection().create_index("post_id", unique=True)


def _reset_mongodb_view_counter_collection() -> None:
    try:
        _get_mongodb_view_counter_collection().drop()
    except Exception:
        return


def _get_mongodb_view_counter(post_id: int) -> int:
    _ensure_mongodb_view_counter_collection()
    row = _get_mongodb_view_counter_collection().find_one(
        {"post_id": int(post_id)},
        {"_id": 0, "counter": 1},
    )
    if row is None:
        return 0
    return int(row.get("counter", 0))


def _set_mongodb_view_counter(post_id: int, value: int) -> None:
    _ensure_mongodb_view_counter_collection()
    _get_mongodb_view_counter_collection().update_one(
        {"post_id": int(post_id)},
        {"$set": {"counter": int(value)}},
        upsert=True,
    )


def _increment_mongodb_view_counter(post_id: int) -> int:
    _ensure_mongodb_view_counter_collection()
    row = _get_mongodb_view_counter_collection().find_one_and_update(
        {"post_id": int(post_id)},
        {"$inc": {"counter": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0, "counter": 1},
    )
    if row is None:
        return 1
    return int(row.get("counter", 1))


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
