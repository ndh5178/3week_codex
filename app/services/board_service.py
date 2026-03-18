"""게시판 서비스 로직을 모아 둔 파일이다.

routes.py가 "어떤 URL로 들어왔는지"를 담당한다면,
이 파일은 "실제로 어떤 일을 해야 하는지"를 담당한다.
"""

from __future__ import annotations

import json
import random
import secrets
import time
from pathlib import Path
from typing import Any

from redis_engine.mini_redis import get_shared_redis


BASE_DIR = Path(__file__).resolve().parents[2]
POSTS_FILE = BASE_DIR / "data" / "posts.json"
REDIS_DUMP_FILE = BASE_DIR / "data" / "redis_dump.json"
DEFAULT_POSTS_PAYLOAD = {
    "posts": [
        {
            "id": 1,
            "title": "Mini Redis Demo",
            "content": "The first request comes from the fake DB.",
            "author": "API Team",
        },
        {
            "id": 2,
            "title": "123",
            "content": "The second request should come from Mini Redis cache.",
            "author": "API Team",
        },
        {
            "id": 3,
            "title": "FastAPI Board",
            "content": "Routes call the service layer, and the service talks to the cache.",
            "author": "API Team",
        },
        {
            "id": 4,
            "title": "새글",
            "content": "새글",
            "author": "동현",
        },
    ]
}

redis = get_shared_redis(data_file=REDIS_DUMP_FILE)

TOP_POSTS_CACHE_KEY = "cache:top_posts"
SESSION_PREFIX = "session:"
POST_PREFIX = "post:"
POST_VIEWS_PREFIX = "views:post:"
SESSION_TTL_SECONDS = 1800
TOP_POSTS_TTL_SECONDS = 120


def list_posts() -> dict[str, Any]:
    """전체 게시글 목록과 출처 통계를 함께 반환한다."""
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
    """인기글 상위 목록을 반환한다."""
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
    """간단한 로그인 세션을 만든다."""
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
    """세션 토큰이 아직 유효한지 확인한다."""
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
    """로그아웃을 처리한다."""
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
    """게시글 하나를 반환한다."""
    post, source = _get_cached_or_db_post(post_id)
    if post is None:
        return None
    return _serialize_post(post, source)


def create_post(payload: dict[str, Any]) -> dict[str, Any]:
    """새 게시글을 만든다."""
    posts = _load_posts()
    next_post_id = max((post["id"] for post in posts), default=0) + 1
    new_post = {
        "id": next_post_id,
        "title": str(payload.get("title", "")).strip(),
        "content": str(payload.get("content", "")).strip(),
        "author": str(payload.get("author", "")).strip() or "익명",
    }

    posts.append(new_post)
    _save_posts(posts)

    redis.delete(TOP_POSTS_CACHE_KEY)
    redis.delete(_build_post_cache_key(next_post_id))

    return {
        **_serialize_post(new_post, "db"),
        "created": True,
    }


def update_post(post_id: int, updates: dict[str, Any]) -> dict[str, Any] | None:
    """게시글을 수정하고 관련 캐시를 무효화한다."""
    posts = _load_posts()
    updated_post: dict[str, Any] | None = None

    for post in posts:
        if post["id"] != post_id:
            continue

        updated_post = {
            "id": post_id,
            "title": str(updates.get("title", post["title"])).strip(),
            "content": str(updates.get("content", post["content"])).strip(),
            "author": str(updates.get("author", post["author"])).strip(),
        }
        post.update(updated_post)
        break

    if updated_post is None:
        return None

    _save_posts(posts)
    cache_invalidated = redis.delete(_build_post_cache_key(post_id))
    top_posts_invalidated = redis.delete(TOP_POSTS_CACHE_KEY)
    return {
        **_serialize_post(updated_post, "db"),
        "cache_invalidated": cache_invalidated,
        "top_posts_invalidated": top_posts_invalidated,
    }


def view_post(post_id: int) -> dict[str, Any] | None:
    """게시글을 열 때 조회수를 1 올린다."""
    post = _load_post_from_fake_db(post_id)
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
    """테스트나 개발 중 캐시를 한 번에 초기화할 때 사용한다."""
    redis.clear()


def generate_demo_posts(count: int = 100) -> dict[str, Any]:
    """시연용 더미 게시글을 한꺼번에 만든다.

    발표 때 사람이 하나씩 글을 쓰지 않아도 되도록,
    제목과 내용이 들어간 게시글 여러 개를 자동 생성한다.
    """
    safe_count = max(1, count)
    posts = _load_posts()
    next_post_id = max((post["id"] for post in posts), default=0) + 1

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
    authors = ["동현", "지수", "민아", "준", "소라", "학생A", "학생B"]

    created_posts: list[dict[str, Any]] = []
    for index in range(safe_count):
        post_id = next_post_id + index
        topic = topic_words[index % len(topic_words)]
        new_post = {
            "id": post_id,
            "title": f"{topic} 데모 글 {post_id}",
            "content": f"{topic}가 실제 서비스에서 어떻게 쓰이는지 설명하는 더미 게시글입니다. 번호는 {post_id}입니다.",
            "author": authors[index % len(authors)],
        }
        posts.append(new_post)
        created_posts.append(new_post)

    _save_posts(posts)
    _clear_post_body_caches()
    redis.delete(TOP_POSTS_CACHE_KEY)

    return {
        "created_count": len(created_posts),
        "total_posts": len(posts),
        "first_created_id": created_posts[0]["id"] if created_posts else None,
        "last_created_id": created_posts[-1]["id"] if created_posts else None,
    }


def randomize_post_views(max_views: int = 1000) -> dict[str, Any]:
    """모든 게시글에 무작위 조회수를 넣는다.

    이렇게 하면 인기글 순위가 바로 생겨서
    Redis 캐시 시연을 더 자연스럽게 할 수 있다.
    """
    safe_max_views = max(1, max_views)
    posts = _load_posts()
    updated_views: list[int] = []

    for post in posts:
        random_views = random.randint(0, safe_max_views)
        redis.set(_build_post_views_key(post["id"]), random_views)
        updated_views.append(random_views)

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
    """조회수 1 증가를 DB 방식과 Redis 방식으로 공정하게 비교한다.

    이전 방식은 "인기글 다시 계산" 과 "이미 계산된 캐시 재사용" 을 비교해서
    캐시의 장점은 보여주지만, 완전히 같은 작업 비교는 아니었다.

    이번 측정은 같은 게시글 하나를 대상으로
    1. DB 파일을 읽고 -> 조회수 1 증가 -> 다시 파일에 저장하는 방식
    2. Redis에서 INCR 한 번 수행하는 방식
    을 각각 여러 번 반복해 평균 시간을 계산한다.
    """
    posts = _load_posts()
    if not posts:
        return {
            "db_average_ms": 0.0,
            "redis_average_ms": 0.0,
            "db_iterations": 0,
            "redis_iterations": 0,
            "speed_ratio": None,
            "target_post_id": None,
            "comparison": "view_increment",
            "message": "비교할 게시글이 없어서 조회수 증가 속도를 측정할 수 없습니다.",
        }

    safe_db_iterations = max(1, db_iterations)
    safe_redis_iterations = max(1, redis_iterations)
    target_post_id = int(posts[0]["id"])
    db_views_field = "db_demo_views"
    original_posts_text = POSTS_FILE.read_text(encoding="utf-8")
    redis_views_key = _build_post_views_key(target_post_id)
    original_redis_views = redis.get(redis_views_key)

    try:
        db_total_ms = 0.0
        for _ in range(safe_db_iterations):
            started_at = time.perf_counter()
            db_posts = _load_posts()
            for post in db_posts:
                if int(post["id"]) == target_post_id:
                    post[db_views_field] = int(post.get(db_views_field, 0)) + 1
                    break
            _save_posts(db_posts)
            db_total_ms += (time.perf_counter() - started_at) * 1000

        redis.set(redis_views_key, 0)

        redis_total_ms = 0.0
        for _ in range(safe_redis_iterations):
            started_at = time.perf_counter()
            redis.incr(redis_views_key)
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
            "message": "같은 게시글의 조회수 1 증가를 DB 파일 저장 방식과 Redis INCR 방식으로 비교한 결과입니다.",
        }
    finally:
        POSTS_FILE.write_text(original_posts_text, encoding="utf-8")
        if original_redis_views is None:
            redis.delete(redis_views_key)
        else:
            redis.set(redis_views_key, original_redis_views)


def reset_demo_database() -> dict[str, Any]:
    """시연용 DB와 Redis 상태를 처음 기준으로 되돌린다.

    이 함수는 발표를 여러 번 반복할 때
    "더미 글 생성", "랜덤 조회수", "세션" 등을 한 번에 정리하는 용도다.
    """
    POSTS_FILE.write_text(
        json.dumps(DEFAULT_POSTS_PAYLOAD, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    reset_cache()
    return {
        "reset": True,
        "post_count": len(DEFAULT_POSTS_PAYLOAD["posts"]),
        "message": "게시글 파일과 Redis 캐시를 초기 상태로 되돌렸습니다.",
    }


def _get_cached_or_db_post(
    post_id: int,
    fallback_post: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """게시글 한 개를 캐시 우선으로 읽는다."""
    cache_key = _build_post_cache_key(post_id)
    cached_post = redis.get(cache_key)
    if isinstance(cached_post, dict):
        return cached_post, "cache"

    post = fallback_post or _load_post_from_fake_db(post_id)
    if post is None:
        return None, "db"

    redis.set(cache_key, post)
    return post, "db"


def _serialize_post(post: dict[str, Any], source: str) -> dict[str, Any]:
    """API 응답용 게시글 구조를 만든다."""
    post_id = int(post["id"])
    return {
        "id": post_id,
        "title": str(post.get("title", "")),
        "content": str(post.get("content", "")),
        "author": str(post.get("author", "")),
        "views": _get_post_views(post_id),
        "source": source,
    }


def _clear_post_body_caches() -> None:
    """게시글 본문 캐시와 인기글 캐시를 지운다.

    조회수는 그대로 두고, "본문을 다시 읽어야 하는 상황"만 만들고 싶을 때 쓴다.
    """
    for post in _load_posts():
        redis.delete(_build_post_cache_key(post["id"]))


def _build_post_cache_key(post_id: int) -> str:
    """게시글 본문 캐시 키를 만든다."""
    return f"{POST_PREFIX}{post_id}"


def _build_post_views_key(post_id: int) -> str:
    """게시글 조회수 키를 만든다."""
    return f"{POST_VIEWS_PREFIX}{post_id}"


def _build_session_key(token: str) -> str:
    """세션 저장 키를 만든다."""
    return f"{SESSION_PREFIX}{token}"


def _resolve_session_key(
    token: str | None = None,
    session_key: str | None = None,
) -> str | None:
    """토큰이나 세션 키 중 실제 사용할 키를 정한다."""
    if session_key:
        return str(session_key)
    if token:
        return _build_session_key(token)
    return None


def _extract_token_from_session_key(session_key: str) -> str:
    """session: 접두어를 제거해 순수 토큰만 꺼낸다."""
    prefix = SESSION_PREFIX
    if session_key.startswith(prefix):
        return session_key[len(prefix):]
    return session_key


def _get_post_views(post_id: int) -> int:
    """현재 게시글 조회수를 읽는다."""
    raw_views = redis.get(_build_post_views_key(post_id))
    try:
        return int(raw_views)
    except (TypeError, ValueError):
        return 0


def _load_post_from_fake_db(post_id: int) -> dict[str, Any] | None:
    """posts.json에서 id가 같은 게시글 하나를 찾는다."""
    for post in _load_posts():
        if post["id"] == post_id:
            return post
    return None


def _load_posts() -> list[dict[str, Any]]:
    """posts.json 파일에서 게시글 목록을 안전하게 읽는다."""
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
                "title": str(raw_post.get("title", "")).strip(),
                "content": str(raw_post.get("content", "")).strip(),
                "author": str(raw_post.get("author", "")).strip() or "익명",
            }
        )

    return posts


def _save_posts(posts: list[dict[str, Any]]) -> None:
    """현재 게시글 목록을 posts.json 파일에 저장한다."""
    payload = {"posts": posts}
    POSTS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
