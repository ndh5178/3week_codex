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


def _parse_bool(raw_value: str | None, default: bool) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


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
    posts_backend: str
    posts_json_path: Path
    posts_sqlite_path: Path
    posts_seed_file: Path
    sqlite_connect_timeout: float
    postgres_dsn: str
    postgres_connect_timeout: int
    postgres_seed_on_prepare: bool
    redis_dump_file: Path | None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        base_dir=BASE_DIR,
        posts_backend=os.getenv("POSTS_BACKEND", "sqlite").strip().lower(),
        posts_json_path=_resolve_path(os.getenv("POSTS_JSON_PATH", "data/posts.json")),
        posts_sqlite_path=_resolve_path(
            os.getenv("POSTS_SQLITE_PATH", "data/posts.sqlite3")
        ),
        posts_seed_file=_resolve_path(os.getenv("POSTS_SEED_FILE", "data/posts.json")),
        sqlite_connect_timeout=_parse_float(
            os.getenv("SQLITE_CONNECT_TIMEOUT"),
            default=3.0,
        ),
        postgres_dsn=os.getenv(
            "POSTGRES_DSN",
            "postgresql://postgres:postgres@localhost:5432/mini_board",
        ),
        postgres_connect_timeout=_parse_int(
            os.getenv("POSTGRES_CONNECT_TIMEOUT"),
            default=3,
        ),
        postgres_seed_on_prepare=_parse_bool(
            os.getenv("POSTGRES_SEED_ON_PREPARE"),
            default=True,
        ),
        redis_dump_file=_resolve_optional_path(os.getenv("REDIS_DUMP_FILE", "")),
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
