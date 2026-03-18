"""Mini Redis의 바깥쪽 진입 클래스다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from redis_engine.commands import RedisCommands
from redis_engine.persistence import RedisPersistence
from redis_engine.storage import MemoryStore


class MiniRedis:
    """API 코드가 직접 사용하는 Mini Redis 진입 클래스다."""

    def __init__(self, data_file: str | Path | None = "data/dump.json") -> None:
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
        """문자열 key에 값을 저장한다."""
        self._commands.set(key, value)

    def get(self, key: str) -> Any | None:
        """key에 해당하는 값을 읽는다. 없으면 None을 돌려준다."""
        return self._commands.get(key)

    def delete(self, key: str) -> bool:
        """key를 삭제하고 성공 여부를 bool로 반환한다."""
        return self._commands.delete(key)

    def exists(self, key: str) -> bool:
        """key가 존재하는지 확인한다."""
        return self._commands.exists(key)

    def incr(self, key: str) -> int:
        """숫자 값을 1 증가시킨다."""
        return self._commands.incr(key)

    def setex(self, key: str, seconds: int, value: Any) -> None:
        """값과 TTL을 함께 저장한다."""
        self._commands.setex(key, seconds, value)

    def clear(self) -> None:
        """모든 key와 TTL 정보를 비운다."""
        self._storage.clear()

    def save(self) -> None:
        """현재 상태를 즉시 파일에 저장한다."""
        self._storage.persist_now()


_shared_instance: MiniRedis | None = None


def get_shared_redis(data_file: str | Path | None = "data/dump.json") -> MiniRedis:
    """앱 전체에서 공유하는 MiniRedis 인스턴스를 반환한다."""
    global _shared_instance

    if _shared_instance is None:
        _shared_instance = MiniRedis(data_file=data_file)

    return _shared_instance
