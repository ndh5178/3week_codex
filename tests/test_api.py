
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.board_service import reset_cache


client = TestClient(app)
POSTS_FILE = Path(__file__).resolve().parents[1] / "data" / "posts.json"
ORIGINAL_POSTS_TEXT = POSTS_FILE.read_text(encoding="utf-8")


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
