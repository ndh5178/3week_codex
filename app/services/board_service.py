from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, UTC
import statistics
import secrets
import time
from pathlib import Path
from typing import Any

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
TOP_POSTS_TTL_SECONDS = 120
VIEW_BENCHMARK_JSON_FILE = settings.base_dir / "data" / "view_benchmark_counter.json"


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
    elif settings.posts_backend == "mongodb":
        posts_label = "MongoDB server"
        posts_storage = "server"
        posts_path = f"{settings.mongodb_uri}/{settings.mongodb_database}.{settings.mongodb_collection}"

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
    _reset_db_view_benchmark_store()


def count_posts() -> int:
    return posts_repository.count()


def generate_demo_posts(count: int = 100) -> dict[str, Any]:
    """발표용 더미 게시글을 여러 개 자동으로 만든다."""
    safe_count = max(1, count)
    topic_words = [
        "Redis 캐시",
        "조회수 카운터",
        "세션 저장",
        "인기글 계산",
        "FastAPI 라우트",
        "메모리 저장소",
        "TTL 만료",
        "캐시 무효화",
    ]
    authors = ["동현", "지민", "민아", "준", "소라", "학생A", "학생B"]

    first_created_id: int | None = None
    last_created_id: int | None = None

    for index in range(safe_count):
        topic = topic_words[index % len(topic_words)]
        created_post = posts_repository.create_post(
            {
                "title": f"{topic} 데모 글 {index + 1}",
                "content": (
                    f"{topic}가 실제 서비스에서 어떻게 동작하는지 설명하는 "
                    f"자동 생성 게시글입니다. 순번은 {index + 1}번입니다."
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
    """모든 게시글의 조회수를 무작위 값으로 채운다."""
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
    """조회수 1 증가를 디스크 저장 방식과 Redis 메모리 방식으로 비교한다."""
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
            "message": "비교할 게시글이 없어서 속도를 측정할 수 없습니다.",
        }

    target_post_id = int(posts[0]["id"])
    safe_db_iterations = max(1, db_iterations)
    safe_redis_iterations = max(1, redis_iterations)
    redis_key = _build_post_views_key(target_post_id)
    original_redis_views = redis.get(redis_key)
    original_db_counter = _get_db_view_counter(target_post_id)

    try:
        db_total_ms = 0.0
        for _ in range(safe_db_iterations):
            started_at = time.perf_counter()
            _increment_db_view_counter(target_post_id)
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
            "message": "같은 게시글의 조회수 1 증가를 디스크 저장 방식과 Redis INCR 방식으로 비교한 결과입니다.",
        }
    finally:
        _set_db_view_counter(target_post_id, original_db_counter)
        if original_redis_views is None:
            redis.delete(redis_key)
        else:
            redis.set(redis_key, original_redis_views)


def reset_demo_database() -> dict[str, Any]:
    """게시글 저장소와 Redis 상태를 데모 초기값으로 되돌린다."""
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


def _get_db_view_counter(post_id: int) -> int:
    """비교용 디스크 카운터의 현재 값을 읽는다."""
    if settings.posts_backend == "sqlite":
        return _get_sqlite_view_counter(post_id)
    if settings.posts_backend == "postgres":
        return _get_postgres_view_counter(post_id)
    if settings.posts_backend == "mongodb":
        return _get_mongodb_view_counter(post_id)
    return _get_json_view_counter(post_id)


def _set_db_view_counter(post_id: int, value: int) -> None:
    """비교용 디스크 카운터를 원하는 값으로 되돌린다."""
    if settings.posts_backend == "sqlite":
        _set_sqlite_view_counter(post_id, value)
        return
    if settings.posts_backend == "postgres":
        _set_postgres_view_counter(post_id, value)
        return
    if settings.posts_backend == "mongodb":
        _set_mongodb_view_counter(post_id, value)
        return
    _set_json_view_counter(post_id, value)


def _increment_db_view_counter(post_id: int) -> int:
    """비교용 디스크 카운터를 1 올린다."""
    if settings.posts_backend == "sqlite":
        return _increment_sqlite_view_counter(post_id)
    if settings.posts_backend == "postgres":
        return _increment_postgres_view_counter(post_id)
    if settings.posts_backend == "mongodb":
        return _increment_mongodb_view_counter(post_id)
    return _increment_json_view_counter(post_id)


def _reset_db_view_benchmark_store() -> None:
    """속도 비교용 디스크 카운터 저장소를 초기화한다."""
    if settings.posts_backend == "sqlite":
        with sqlite3.connect(settings.posts_sqlite_path, timeout=settings.sqlite_connect_timeout) as conn:
            conn.execute("DROP TABLE IF EXISTS view_benchmark_counters")
        return
    if settings.posts_backend == "postgres":
        try:
            import psycopg

            with psycopg.connect(
                settings.postgres_dsn,
                connect_timeout=settings.postgres_connect_timeout,
            ) as conn, conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS view_benchmark_counters")
        except Exception:
            return
        return
    if settings.posts_backend == "mongodb":
        try:
            _get_mongodb_view_counter_collection().drop()
        except Exception:
            return
        return
    if VIEW_BENCHMARK_JSON_FILE.exists():
        VIEW_BENCHMARK_JSON_FILE.unlink()


def _ensure_sqlite_view_counter_table() -> None:
    settings.posts_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.posts_sqlite_path, timeout=settings.sqlite_connect_timeout) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS view_benchmark_counters (
                post_id INTEGER PRIMARY KEY,
                counter INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def _get_sqlite_view_counter(post_id: int) -> int:
    _ensure_sqlite_view_counter_table()
    with sqlite3.connect(settings.posts_sqlite_path, timeout=settings.sqlite_connect_timeout) as conn:
        row = conn.execute(
            "SELECT counter FROM view_benchmark_counters WHERE post_id = ?",
            (post_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def _set_sqlite_view_counter(post_id: int, value: int) -> None:
    _ensure_sqlite_view_counter_table()
    with sqlite3.connect(settings.posts_sqlite_path, timeout=settings.sqlite_connect_timeout) as conn:
        conn.execute(
            """
            INSERT INTO view_benchmark_counters (post_id, counter)
            VALUES (?, ?)
            ON CONFLICT(post_id) DO UPDATE SET counter = excluded.counter
            """,
            (post_id, int(value)),
        )


def _increment_sqlite_view_counter(post_id: int) -> int:
    _ensure_sqlite_view_counter_table()
    with sqlite3.connect(settings.posts_sqlite_path, timeout=settings.sqlite_connect_timeout) as conn:
        conn.execute(
            """
            INSERT INTO view_benchmark_counters (post_id, counter)
            VALUES (?, 1)
            ON CONFLICT(post_id) DO UPDATE SET counter = counter + 1
            """,
            (post_id,),
        )
        row = conn.execute(
            "SELECT counter FROM view_benchmark_counters WHERE post_id = ?",
            (post_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def _read_json_view_counter_store() -> dict[str, int]:
    if not VIEW_BENCHMARK_JSON_FILE.exists():
        return {}

    try:
        payload = json.loads(VIEW_BENCHMARK_JSON_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    normalized: dict[str, int] = {}
    for key, value in payload.items():
        try:
            normalized[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return normalized


def _write_json_view_counter_store(payload: dict[str, int]) -> None:
    VIEW_BENCHMARK_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    VIEW_BENCHMARK_JSON_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_json_view_counter(post_id: int) -> int:
    return int(_read_json_view_counter_store().get(str(post_id), 0))


def _set_json_view_counter(post_id: int, value: int) -> None:
    payload = _read_json_view_counter_store()
    payload[str(post_id)] = int(value)
    _write_json_view_counter_store(payload)


def _increment_json_view_counter(post_id: int) -> int:
    payload = _read_json_view_counter_store()
    next_value = int(payload.get(str(post_id), 0)) + 1
    payload[str(post_id)] = next_value
    _write_json_view_counter_store(payload)
    return next_value


def _ensure_postgres_view_counter_table() -> None:
    import psycopg

    with psycopg.connect(
        settings.postgres_dsn,
        connect_timeout=settings.postgres_connect_timeout,
    ) as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS view_benchmark_counters (
                post_id INTEGER PRIMARY KEY,
                counter INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def _get_postgres_view_counter(post_id: int) -> int:
    import psycopg

    _ensure_postgres_view_counter_table()
    with psycopg.connect(
        settings.postgres_dsn,
        connect_timeout=settings.postgres_connect_timeout,
    ) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT counter FROM view_benchmark_counters WHERE post_id = %s",
            (post_id,),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _set_postgres_view_counter(post_id: int, value: int) -> None:
    import psycopg

    _ensure_postgres_view_counter_table()
    with psycopg.connect(
        settings.postgres_dsn,
        connect_timeout=settings.postgres_connect_timeout,
    ) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO view_benchmark_counters (post_id, counter)
            VALUES (%s, %s)
            ON CONFLICT (post_id) DO UPDATE SET counter = EXCLUDED.counter
            """,
            (post_id, int(value)),
        )


def _increment_postgres_view_counter(post_id: int) -> int:
    import psycopg

    _ensure_postgres_view_counter_table()
    with psycopg.connect(
        settings.postgres_dsn,
        connect_timeout=settings.postgres_connect_timeout,
    ) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO view_benchmark_counters (post_id, counter)
            VALUES (%s, 1)
            ON CONFLICT (post_id) DO UPDATE SET counter = view_benchmark_counters.counter + 1
            RETURNING counter
            """,
            (post_id,),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _get_mongodb_view_counter_collection():
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise RuntimeError(
            "pymongo is required for the MongoDB view counter benchmark."
        ) from exc

    client = MongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=settings.mongodb_connect_timeout_ms,
        connectTimeoutMS=settings.mongodb_connect_timeout_ms,
    )
    database = client[settings.mongodb_database]
    return database[f"{settings.mongodb_collection}_view_benchmark_counters"]


def _ensure_mongodb_view_counter_collection() -> None:
    collection = _get_mongodb_view_counter_collection()
    collection.create_index("post_id", unique=True)


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
    from pymongo import ReturnDocument

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
