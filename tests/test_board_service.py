from __future__ import annotations

import copy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import pymongo  # type: ignore # noqa: F401
except ImportError:
    sys.modules["pymongo"] = types.SimpleNamespace(
        ReturnDocument=types.SimpleNamespace(AFTER="after")
    )

try:
    import httpx  # type: ignore # noqa: F401
except ImportError:
    class _DummyClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    sys.modules["httpx"] = types.SimpleNamespace(Client=_DummyClient)

from app.services import board_service
from redis_engine.mini_redis import MiniRedis


class FakePostsRepository:
    def __init__(self, posts: list[dict[str, object]]) -> None:
        self._posts = {int(post["id"]): copy.deepcopy(post) for post in posts}
        self.get_post_calls = 0
        self.list_posts_calls = 0

    def list_posts(self) -> list[dict[str, object]]:
        self.list_posts_calls += 1
        return [copy.deepcopy(self._posts[post_id]) for post_id in sorted(self._posts)]

    def get_post(self, post_id: int) -> dict[str, object] | None:
        self.get_post_calls += 1
        post = self._posts.get(int(post_id))
        return copy.deepcopy(post) if post is not None else None

    def update_post(self, post_id: int, payload: dict[str, object]) -> dict[str, object] | None:
        current = self._posts.get(int(post_id))
        if current is None:
            return None

        updated = {
            **current,
            "title": str(payload.get("title", current["title"])),
            "content": str(payload.get("content", current["content"])),
            "author": str(payload.get("author", current["author"])),
        }
        self._posts[int(post_id)] = copy.deepcopy(updated)
        return copy.deepcopy(updated)

    def create_post(self, payload: dict[str, object]) -> dict[str, object]:
        next_id = max(self._posts, default=0) + 1
        created = {
            "id": next_id,
            "title": str(payload["title"]),
            "content": str(payload["content"]),
            "author": str(payload["author"]),
        }
        self._posts[next_id] = copy.deepcopy(created)
        return copy.deepcopy(created)

    def delete_post(self, post_id: int) -> dict[str, object] | None:
        post = self._posts.pop(int(post_id), None)
        return copy.deepcopy(post) if post is not None else None


class BoardServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = MiniRedis(data_file=None)
        self.posts_repository = FakePostsRepository(
            [
                {"id": 1, "title": "First", "content": "Alpha", "author": "Kim"},
                {"id": 2, "title": "Second", "content": "Beta", "author": "Lee"},
            ]
        )

        self.redis_patch = patch.object(board_service, "redis", self.redis)
        self.repo_patch = patch.object(board_service, "posts_repository", self.posts_repository)
        self.redis_patch.start()
        self.repo_patch.start()
        self.addCleanup(self.redis_patch.stop)
        self.addCleanup(self.repo_patch.stop)

    def test_get_post_uses_cache_after_first_read(self) -> None:
        first = board_service.get_post(1)
        second = board_service.get_post(1)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first["source"], "db")
        self.assertEqual(second["source"], "cache")
        self.assertEqual(self.posts_repository.get_post_calls, 1)

        cache_status = board_service.get_post_cache_status(1)
        self.assertTrue(cache_status["exists"])

    def test_update_post_invalidates_cached_entry(self) -> None:
        board_service.get_post(1)

        updated = board_service.update_post(
            1,
            {
                "title": "Updated title",
                "content": "Updated content",
                "author": "Park",
            },
        )

        refreshed = board_service.get_post(1)
        cached_again = board_service.get_post(1)

        self.assertIsNotNone(updated)
        self.assertTrue(updated["cache_invalidated"])
        self.assertEqual(refreshed["source"], "db")
        self.assertEqual(refreshed["title"], "Updated title")
        self.assertEqual(cached_again["source"], "cache")

    def test_login_check_and_logout_flow(self) -> None:
        login_result = board_service.login("alice")
        token = str(login_result["token"])

        session_ok = board_service.check_session(token)
        logout_result = board_service.logout(token=token)
        session_after_logout = board_service.check_session(token)

        self.assertEqual(login_result["source"], "redis")
        self.assertTrue(session_ok["authenticated"])
        self.assertTrue(logout_result["deleted"])
        self.assertFalse(session_after_logout["authenticated"])

    def test_view_post_increments_views_and_invalidates_top_posts(self) -> None:
        board_service.get_post(1)
        self.redis.setex(
            board_service.TOP_POSTS_CACHE_KEY,
            board_service.TOP_POSTS_TTL_SECONDS,
            [{"id": 1, "title": "cached top"}],
        )

        viewed = board_service.view_post(1)

        self.assertIsNotNone(viewed)
        self.assertEqual(viewed["live_access"]["source"], "cache")
        self.assertEqual(viewed["views"], 1)
        self.assertTrue(viewed["top_posts_invalidated"])
        self.assertIsNone(self.redis.get(board_service.TOP_POSTS_CACHE_KEY))


if __name__ == "__main__":
    unittest.main()
