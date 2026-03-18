
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.board_service import reset_cache
from redis_engine.mini_redis import get_shared_redis


client = TestClient(app)
POSTS_FILE = Path(__file__).resolve().parents[1] / "data" / "posts.json"
ORIGINAL_POSTS_TEXT = POSTS_FILE.read_text(encoding="utf-8")
redis = get_shared_redis()


def setup_function() -> None:
    reset_cache()
    POSTS_FILE.write_text(ORIGINAL_POSTS_TEXT, encoding="utf-8")


def teardown_function() -> None:
    reset_cache()
    POSTS_FILE.write_text(ORIGINAL_POSTS_TEXT, encoding="utf-8")


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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


def test_posts_list_endpoint_shows_cache_and_db_flow() -> None:
    first_response = client.get("/posts")
    second_response = client.get("/posts")

    assert first_response.status_code == 200
    assert len(first_response.json()["posts"]) == 3
    assert first_response.json()["sources"] == {"cache": 0, "db": 3}
    assert second_response.status_code == 200
    assert second_response.json()["sources"] == {"cache": 3, "db": 0}


def test_top_posts_uses_cache_and_view_invalidates_it() -> None:
    first_response = client.get("/top-posts")
    second_response = client.get("/top-posts")
    view_response = client.post("/posts/2/view")
    refreshed_response = client.get("/top-posts")

    assert first_response.status_code == 200
    assert first_response.json()["source"] == "computed"
    assert second_response.status_code == 200
    assert second_response.json()["source"] == "cache"
    assert view_response.status_code == 200
    assert view_response.json()["views"] == 1
    assert view_response.json()["top_posts_cache_invalidated"] is True
    assert refreshed_response.status_code == 200
    assert refreshed_response.json()["source"] == "computed"
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
    assert logout_response.json()["logged_out"] is True
    assert redis.exists(session_key) is False
