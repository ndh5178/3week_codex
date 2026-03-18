"""Mini Redis의 가장 작은 핵심 엔진."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from redis_engine.commands import RedisCommands
from redis_engine.persistence import RedisPersistence
from redis_engine.storage import MemoryStore


class MiniRedis:
    """API 코드가 사용하는 Mini Redis 진입점."""

    def __init__(self, data_file: str | Path | None = "data/redis_dump.json") -> None:
        self._persistence = RedisPersistence(data_file) if data_file is not None else None
        initial_store: dict[str, Any] = {}
        initial_expire_at: dict[str, float] = {}
        on_change = None

        if self._persistence is not None:
            initial_store, initial_expire_at = self._persistence.load()
            on_change = self._persistence.save

        self._storage = MemoryStore(
            initial_store,
            initial_expire_at,
            on_change=on_change,
        )
        self._commands = RedisCommands(self._storage)
        self._store = self._storage.store
        self._expire_at = self._storage.expire_at
        self._lock = self._storage.lock

    def set(self, key: str, value: Any) -> None:
        self._commands.set(key, value)

    def get(self, key: str) -> Any | None:
        return self._commands.get(key)

    def delete(self, key: str) -> bool:
        return self._commands.delete(key)

    def exists(self, key: str) -> bool:
        return self._commands.exists(key)

    def incr(self, key: str) -> int:
        return self._commands.incr(key)

    def setex(self, key: str, seconds: int, value: Any) -> None:
        self._commands.setex(key, seconds, value)

    def ttl(self, key: str) -> int:
        return self._commands.ttl(key)

    def clear(self) -> None:
        self._storage.clear()

    def save(self) -> None:
        self._storage.persist_now()


_shared_instances: dict[str, MiniRedis] = {}
_shared_instances_lock = RLock()


def _normalize_shared_key(data_file: str | Path | None) -> str:
    if data_file is None:
        return "__memory__"

    path = Path(data_file)
    if path.is_absolute():
        return str(path)
    return str(path.resolve())


def get_shared_redis(data_file: str | Path | None = "data/redis_dump.json") -> MiniRedis:
    shared_key = _normalize_shared_key(data_file)

    with _shared_instances_lock:
        shared_instance = _shared_instances.get(shared_key)
        if shared_instance is None:
            shared_instance = MiniRedis(data_file=data_file)
            _shared_instances[shared_key] = shared_instance

    return shared_instance


def reset_shared_redis(data_file: str | Path | None = None) -> None:
    with _shared_instances_lock:
        if data_file is None:
            _shared_instances.clear()
            return

        _shared_instances.pop(_normalize_shared_key(data_file), None)
