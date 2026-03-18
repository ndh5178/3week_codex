from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from redis_engine.mini_redis import get_shared_redis


BASE_DIR = Path(__file__).resolve().parents[2]
POSTS_FILE = BASE_DIR / "data" / "posts.json"
REDIS_DUMP_FILE = BASE_DIR / "data" / "redis_dump.json"

# 앱 전체에서 Mini Redis 인스턴스는 하나만 공유한다.
redis = get_shared_redis(data_file=REDIS_DUMP_FILE)

TOP_POSTS_CACHE_KEY = "cache:top_posts"
SESSION_PREFIX = "session:"
POST_PREFIX = "post:"
POST_VIEWS_PREFIX = "views:post:"
SESSION_TTL_SECONDS = 1800
TOP_POSTS_TTL_SECONDS = 120


def list_posts() -> dict[str, Any]:
    """전체 게시글 목록과 출처 통계를 함께 반환한다.

    각 게시글은 Redis 캐시를 먼저 확인하므로,
    화면에서 cache/db 흐름을 함께 보여줄 수 있다.
    """
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
    """상위 인기글 목록을 반환한다.

    먼저 Redis에서 캐시된 인기글을 찾고,
    없으면 게시글 목록을 다시 계산한 뒤 캐시에 저장한다.
    """
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
    """세션 토큰이나 세션 키를 이용해 로그아웃 처리한다."""
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

    # 새 글이 생기면 목록과 인기글 결과가 달라질 수 있으므로 캐시를 비운다.
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
    """게시글 조회수를 1 올리고 최신 게시글 상태를 반환한다."""
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
    """테스트나 로컬 실행 중 캐시를 초기화할 때 사용한다."""
    redis.clear()


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
    """API 응답에 맞는 게시글 구조를 만든다."""
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
    """토큰이나 세션 키 중 실제 사용할 세션 키를 정한다."""
    if session_key:
        return str(session_key)
    if token:
        return _build_session_key(token)
    return None


def _extract_token_from_session_key(session_key: str) -> str:
    """session: 접두어를 제거해 순수 토큰을 만든다."""
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
    """파일에서 게시글 목록을 안전하게 읽는다."""
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
    """현재 게시글 목록을 파일에 저장한다."""
    payload = {"posts": posts}
    POSTS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
