from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.board_service import reset_cache
from redis_engine.mini_redis import get_shared_redis


client = TestClient(app)
POSTS_FILE = Path(__file__).resolve().parents[1] / "data" / "posts.json"
ORIGINAL_POSTS_TEXT = POSTS_FILE.read_text(encoding="utf-8")
ORIGINAL_POSTS_COUNT = len(json.loads(ORIGINAL_POSTS_TEXT)["posts"])
redis = get_shared_redis()


def setup_function() -> None:
    """각 테스트 전에 캐시와 게시글 파일을 원래 상태로 되돌린다."""
    reset_cache()
    POSTS_FILE.write_text(ORIGINAL_POSTS_TEXT, encoding="utf-8")


def teardown_function() -> None:
    """각 테스트 뒤에도 원래 상태를 복구해 다음 테스트에 영향이 없게 한다."""
    reset_cache()
    POSTS_FILE.write_text(ORIGINAL_POSTS_TEXT, encoding="utf-8")


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_posts_list_returns_all_posts_and_source_summary() -> None:
    first_response = client.get("/posts")
    second_response = client.get("/posts")

    assert first_response.status_code == 200
    assert len(first_response.json()["posts"]) == ORIGINAL_POSTS_COUNT
    assert first_response.json()["sources"] == {"cache": 0, "db": ORIGINAL_POSTS_COUNT}
    assert second_response.status_code == 200
    assert second_response.json()["sources"] == {"cache": ORIGINAL_POSTS_COUNT, "db": 0}


def test_posts_endpoint_uses_cache_after_first_request() -> None:
    first_response = client.get("/posts/1")
    second_response = client.get("/posts/1")

    assert first_response.status_code == 200
    assert first_response.json()["source"] == "db"
    assert second_response.status_code == 200
    assert second_response.json()["source"] == "cache"
    assert second_response.json()["id"] == 1


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


def test_update_post_invalidates_cache() -> None:
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
