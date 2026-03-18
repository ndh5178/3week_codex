from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from redis_engine.mini_redis import get_shared_redis


settings = get_settings()
redis = get_shared_redis(data_file=settings.redis_dump_file)


def set_value(key: str, value: Any) -> dict[str, Any]:
    normalized_key = str(key)
    redis.set(normalized_key, value)
    return {
        "key": normalized_key,
        "value": value,
        "stored": True,
    }


def get_value(key: str) -> dict[str, Any]:
    normalized_key = str(key)
    value = redis.get(normalized_key)
    exists = redis.exists(normalized_key)
    return {
        "key": normalized_key,
        "value": value,
        "exists": exists,
    }


def exists_value(key: str) -> dict[str, Any]:
    normalized_key = str(key)
    return {
        "key": normalized_key,
        "exists": redis.exists(normalized_key),
    }


def delete_value(key: str) -> dict[str, Any]:
    normalized_key = str(key)
    return {
        "key": normalized_key,
        "deleted": redis.delete(normalized_key),
    }


def incr_value(key: str) -> dict[str, Any]:
    normalized_key = str(key)
    value = redis.incr(normalized_key)
    return {
        "key": normalized_key,
        "value": value,
    }


def set_value_with_ttl(key: str, seconds: int, value: Any) -> dict[str, Any]:
    normalized_key = str(key)
    redis.setex(normalized_key, seconds, value)
    return {
        "key": normalized_key,
        "value": value,
        "ttl_seconds": seconds,
        "stored": True,
    }


def clear_values() -> dict[str, bool]:
    redis.clear()
    return {"cleared": True}


def save_values() -> None:
    """현재 Redis 메모리 상태를 dump 파일에 한 번 더 저장한다."""
    redis.save()
