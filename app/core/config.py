from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _resolve_optional_path(raw_path: str | None) -> Path | None:
    if raw_path is None:
        return None

    normalized = raw_path.strip()
    if not normalized:
        return None

    return _resolve_path(normalized)


def _parse_int(raw_value: str | None, default: int) -> int:
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _parse_float(raw_value: str | None, default: float) -> float:
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    posts_seed_file: Path
    mongodb_uri: str
    mongodb_database: str
    mongodb_collection: str
    mongodb_connect_timeout_ms: int
    mongodb_seed_on_prepare: bool
    mini_redis_backend: str
    mini_redis_url: str
    mini_redis_timeout_seconds: float
    redis_dump_file: Path | None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        base_dir=BASE_DIR,
        posts_seed_file=_resolve_path(os.getenv("POSTS_SEED_FILE", "data/posts.json")),
        mongodb_uri=os.getenv("MONGODB_URI", "mongodb://localhost:27017").strip(),
        mongodb_database=os.getenv("MONGODB_DATABASE", "mini_board").strip(),
        mongodb_collection=os.getenv("MONGODB_COLLECTION", "posts").strip(),
        mongodb_connect_timeout_ms=_parse_int(
            os.getenv("MONGODB_CONNECT_TIMEOUT_MS"),
            default=3000,
        ),
        mongodb_seed_on_prepare=os.getenv("MONGODB_SEED_ON_PREPARE", "true").strip().lower()
        in {"1", "true", "yes", "on"},
        mini_redis_backend=os.getenv("MINI_REDIS_BACKEND", "remote").strip().lower(),
        mini_redis_url=os.getenv("MINI_REDIS_URL", "http://127.0.0.1:6380").strip(),
        mini_redis_timeout_seconds=_parse_float(
            os.getenv("MINI_REDIS_TIMEOUT_SECONDS"),
            default=3.0,
        ),
        redis_dump_file=_resolve_optional_path(
            os.getenv("REDIS_DUMP_FILE", "data/redis_dump.json")
        ),
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
