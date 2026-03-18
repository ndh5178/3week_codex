from __future__ import annotations

import os
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
RUNTIME_DIR = TESTS_DIR / ".runtime"

os.environ["POSTS_BACKEND"] = "sqlite"
os.environ["POSTS_SEED_FILE"] = str(FIXTURES_DIR / "posts_seed.json")
os.environ["POSTS_JSON_PATH"] = str(RUNTIME_DIR / "posts.json")
os.environ["POSTS_SQLITE_PATH"] = str(RUNTIME_DIR / "posts.sqlite3")
os.environ["REDIS_DUMP_FILE"] = ""

from app.core.config import reset_settings_cache
from app.repositories.posts import reset_posts_repository_cache
from redis_engine.mini_redis import reset_shared_redis


reset_settings_cache()
reset_posts_repository_cache()
reset_shared_redis()

from app.services.board_service import reset_cache, reset_posts_store


@pytest.fixture(autouse=True)
def reset_runtime_state() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    reset_posts_store()
    reset_cache()
    yield
    reset_cache()
    reset_posts_store()
