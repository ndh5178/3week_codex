from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

import app.services.board_service as board_service
from app.core.config import get_settings
from app.main import app
from app.services.board_service import count_posts
from redis_engine.mini_redis import get_shared_redis


client = TestClient(app)
settings = get_settings()
ORIGINAL_POSTS_COUNT = count_posts()
redis = get_shared_redis(data_file=settings.redis_dump_file)


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_storage_summary_reports_sqlite_disk_and_memory_cache() -> None:
    response = client.get("/storage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["posts"]["backend"] == "sqlite"
    assert payload["posts"]["storage"] == "disk"
    assert payload["posts"]["path"].endswith("posts.sqlite3")
    assert payload["cache"]["backend"] == "mini-redis"
    assert payload["cache"]["storage"] == "memory"
    assert payload["cache"]["persistence_enabled"] is False


def test_posts_list_returns_all_posts_and_source_summary() -> None:
    first_response = client.get("/posts")
    second_response = client.get("/posts")

    assert first_response.status_code == 200
    assert len(first_response.json()["posts"]) == ORIGINAL_POSTS_COUNT
    assert first_response.json()["list_source"] == "db"
    assert first_response.json()["sources"] == {"cache": 0, "db": ORIGINAL_POSTS_COUNT}
    assert second_response.status_code == 200
    assert second_response.json()["list_source"] == "cache"
    assert second_response.json()["sources"] == {"cache": ORIGINAL_POSTS_COUNT, "db": 0}


def test_posts_endpoint_uses_cache_after_first_request() -> None:
    first_response = client.get("/posts/1")
    second_response = client.get("/posts/1")

    assert first_response.status_code == 200
    assert first_response.json()["source"] == "db"
    assert second_response.status_code == 200
    assert second_response.json()["source"] == "cache"
    assert second_response.json()["id"] == 1


def test_posts_list_endpoint_uses_list_cache_after_first_request(monkeypatch) -> None:
    calls = {"count": 0}
    original_list_posts = board_service.posts_repository.list_posts

    def wrapped_list_posts():
        calls["count"] += 1
        return original_list_posts()

    monkeypatch.setattr(board_service.posts_repository, "list_posts", wrapped_list_posts)

    first_response = client.get("/posts")
    second_response = client.get("/posts")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert calls["count"] == 1
    assert first_response.json()["list_source"] == "db"
    assert second_response.json()["list_source"] == "cache"


def test_view_endpoint_uses_cache_after_first_open(monkeypatch) -> None:
    calls = {"count": 0}
    original_load_post = board_service._load_post_from_db

    def wrapped_load_post(post_id: int):
        calls["count"] += 1
        return original_load_post(post_id)

    monkeypatch.setattr(board_service, "_load_post_from_db", wrapped_load_post)

    first_response = client.post("/posts/1/view")
    second_response = client.post("/posts/1/view")

    assert first_response.status_code == 200
    assert first_response.json()["source"] == "db"
    assert second_response.status_code == 200
    assert second_response.json()["source"] == "cache"
    assert calls["count"] == 1


def test_missing_post_returns_404() -> None:
    response = client.get("/posts/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Post not found"}


def test_create_post_adds_new_record() -> None:
    create_response = client.post(
        "/posts",
        json={
            "title": "새 글",
            "content": "글쓰기 기능 테스트",
            "author": "WEB Team",
        },
    )
    list_response = client.get("/posts")

    assert create_response.status_code == 200
    assert create_response.json()["created"] is True
    assert create_response.json()["id"] == ORIGINAL_POSTS_COUNT + 1
    assert list_response.status_code == 200
    assert len(list_response.json()["posts"]) == ORIGINAL_POSTS_COUNT + 1

    with sqlite3.connect(settings.posts_sqlite_path) as conn:
        persisted_row = conn.execute(
            "SELECT title, content, author FROM posts WHERE id = ?",
            (ORIGINAL_POSTS_COUNT + 1,),
        ).fetchone()

    assert persisted_row == ("새 글", "글쓰기 기능 테스트", "WEB Team")


def test_update_post_invalidates_cache() -> None:
    client.get("/posts")
    client.get("/posts/1")
    client.get("/posts/1")

    update_response = client.put(
        "/posts/1",
        json={
            "title": "Updated title",
            "content": "Updated content",
            "author": "API Team",
        },
    )
    refreshed_response = client.get("/posts/1")
    cached_response = client.get("/posts/1")

    assert update_response.status_code == 200
    assert update_response.json()["title"] == "Updated title"
    assert update_response.json()["list_cache_invalidated"] is True
    assert update_response.json()["cache_invalidated"] is True
    assert refreshed_response.status_code == 200
    assert refreshed_response.json()["source"] == "db"
    assert refreshed_response.json()["title"] == "Updated title"
    assert cached_response.status_code == 200
    assert cached_response.json()["source"] == "cache"
    assert cached_response.json()["title"] == "Updated title"


def test_top_posts_uses_cache_and_view_invalidates_it() -> None:
    first_response = client.get("/top-posts")
    second_response = client.get("/top-posts")
    view_response = client.post("/posts/2/view")
    refreshed_response = client.get("/top-posts")

    assert first_response.status_code == 200
    assert first_response.json()["source"] == "db"
    assert second_response.status_code == 200
    assert second_response.json()["source"] == "cache"
    assert view_response.status_code == 200
    assert view_response.json()["views"] == 1
    assert view_response.json()["top_posts_invalidated"] is True
    assert refreshed_response.status_code == 200
    assert refreshed_response.json()["source"] == "db"
    assert refreshed_response.json()["posts"][0]["id"] == 2


def test_clear_post_cache_route_clears_selected_post_cache() -> None:
    client.get("/posts/1")
    cached_response = client.get("/posts/1")
    clear_response = client.post("/posts/1/cache/clear")
    refreshed_response = client.get("/posts/1")

    assert cached_response.status_code == 200
    assert cached_response.json()["source"] == "cache"
    assert clear_response.status_code == 200
    assert clear_response.json()["post_cache_deleted"] is True
    assert refreshed_response.status_code == 200
    assert refreshed_response.json()["source"] == "db"


def test_benchmark_route_reports_db_and_cache_timings() -> None:
    response = client.post("/posts/1/benchmark?iterations=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["post_id"] == 1
    assert payload["iterations"] == 5
    assert payload["mode"] == "both"
    assert payload["db"]["source"] == "disk"
    assert payload["db"]["operation"] == "repository.get_post"
    assert payload["cache"]["source"] == "memory"
    assert payload["cache"]["operation"] == "redis.get(post_cache_key)"
    assert payload["db"]["average_ms"] >= 0
    assert payload["cache"]["average_ms"] >= 0
    assert payload["db"]["p95_ms"] >= 0
    assert payload["cache"]["p95_ms"] >= 0
    assert payload["speedup"] >= 0
    assert payload["comparison"]["database_label"] == "SQLite on local disk direct read"
    assert payload["comparison"]["cache_label"] == "Mini Redis in memory direct key lookup"
    assert payload["comparison"]["focus"] == "direct persistent-store read vs direct in-memory cache lookup"


def test_benchmark_route_reports_only_db_timings_in_db_mode() -> None:
    response = client.post("/posts/1/benchmark?iterations=5&mode=db")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "db"
    assert payload["db"]["source"] == "disk"
    assert payload["db"]["operation"] == "repository.get_post"
    assert payload["cache"] is None
    assert payload["speedup"] is None


def test_benchmark_route_reports_only_cache_timings_in_cache_mode() -> None:
    client.post("/posts/1/view")

    response = client.post("/posts/1/benchmark?iterations=5&mode=cache")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "cache"
    assert payload["db"] is None
    assert payload["cache"]["source"] == "memory"
    assert payload["cache"]["operation"] == "redis.get(post_cache_key)"
    assert payload["speedup"] is None


def test_benchmark_route_returns_400_when_cache_mode_runs_on_empty_cache() -> None:
    client.post("/posts/1/cache/clear")

    response = client.post("/posts/1/benchmark?iterations=5&mode=cache")

    assert response.status_code == 400
    assert response.json() == {"detail": "Post cache is empty"}


def test_login_and_logout_manage_session_in_redis() -> None:
    login_response = client.post("/login", json={"username": "student"})

    assert login_response.status_code == 200
    assert login_response.json()["username"] == "student"

    token = login_response.json()["token"]
    session_key = f"session:{token}"

    assert redis.exists(session_key) is True

    logout_response = client.post("/logout", json={"token": token})

    assert logout_response.status_code == 200
    assert logout_response.json()["deleted"] is True
    assert redis.exists(session_key) is False


def test_session_check_returns_authenticated_user_for_valid_token() -> None:
    login_response = client.post("/login", json={"username": "donghyun"})
    token = login_response.json()["token"]

    session_response = client.post("/session/check", json={"token": token})

    assert session_response.status_code == 200
    assert session_response.json()["authenticated"] is True
    assert session_response.json()["username"] == "donghyun"
    assert session_response.json()["token"] == token


def test_session_check_returns_logged_out_state_for_invalid_token() -> None:
    response = client.post("/session/check", json={"token": "missing-token"})

    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert response.json()["username"] is None


def test_generic_redis_endpoints_support_external_key_value_usage() -> None:
    set_response = client.post(
        "/redis/set",
        json={
            "key": "demo:user",
            "value": {"name": "alice", "role": "admin"},
        },
    )
    get_response = client.get("/redis/get", params={"key": "demo:user"})
    exists_response = client.get("/redis/exists", params={"key": "demo:user"})
    delete_response = client.post("/redis/delete", json={"key": "demo:user"})
    missing_response = client.get("/redis/get", params={"key": "demo:user"})

    assert set_response.status_code == 200
    assert set_response.json()["stored"] is True
    assert get_response.status_code == 200
    assert get_response.json()["value"] == {"name": "alice", "role": "admin"}
    assert get_response.json()["exists"] is True
    assert exists_response.status_code == 200
    assert exists_response.json() == {"key": "demo:user", "exists": True}
    assert delete_response.status_code == 200
    assert delete_response.json() == {"key": "demo:user", "deleted": True}
    assert missing_response.status_code == 200
    assert missing_response.json() == {"key": "demo:user", "value": None, "exists": False}


def test_generic_redis_endpoints_support_ttl_incr_and_clear() -> None:
    ttl_response = client.post(
        "/redis/setex",
        json={
            "key": "otp:alice",
            "seconds": 30,
            "value": "9999",
        },
    )
    first_incr_response = client.post("/redis/incr", json={"key": "counter"})
    second_incr_response = client.post("/redis/incr", json={"key": "counter"})
    clear_response = client.post("/redis/clear")
    counter_after_clear = client.get("/redis/get", params={"key": "counter"})
    otp_after_clear = client.get("/redis/get", params={"key": "otp:alice"})

    assert ttl_response.status_code == 200
    assert ttl_response.json()["ttl_seconds"] == 30
    assert ttl_response.json()["stored"] is True
    assert first_incr_response.status_code == 200
    assert first_incr_response.json() == {"key": "counter", "value": 1}
    assert second_incr_response.status_code == 200
    assert second_incr_response.json() == {"key": "counter", "value": 2}
    assert clear_response.status_code == 200
    assert clear_response.json() == {"cleared": True}
    assert counter_after_clear.status_code == 200
    assert counter_after_clear.json()["exists"] is False
    assert otp_after_clear.status_code == 200
    assert otp_after_clear.json()["exists"] is False


def test_generic_redis_incr_returns_400_for_non_integer_value() -> None:
    client.post(
        "/redis/set",
        json={
            "key": "counter",
            "value": "not-a-number",
        },
    )

    response = client.post("/redis/incr", json={"key": "counter"})

    assert response.status_code == 400
    assert response.json() == {"detail": "value is not an integer"}
