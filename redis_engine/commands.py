"""Mini Redis 명령 규칙을 처리하는 레이어다."""

from __future__ import annotations

import json
from typing import Any

from redis_engine.storage import MemoryStore


class RedisCommands:
    """MemoryStore를 실제 Redis처럼 보이게 감싸는 클래스다."""

    def __init__(self, storage: MemoryStore) -> None:
        self._storage = storage

    def get(self, key: str) -> Any | None:
        """key로 값을 읽는다."""
        normalized_key = self._normalize_key(key)
        return self._storage.get(normalized_key)

    def set(self, key: str, value: Any) -> None:
        """값을 저장한다."""
        normalized_key = self._normalize_key(key)
        self._ensure_json_serializable(value)
        self._storage.set(normalized_key, value)

    def delete(self, key: str) -> bool:
        """key를 삭제하고 성공 여부를 bool로 반환한다."""
        normalized_key = self._normalize_key(key)
        return self._storage.delete(normalized_key) > 0

    def exists(self, key: str) -> bool:
        """key 존재 여부를 bool로 반환한다."""
        normalized_key = self._normalize_key(key)
        return self._storage.exists(normalized_key) > 0

    def incr(self, key: str) -> int:
        """숫자 값을 1 증가시킨다."""
        normalized_key = self._normalize_key(key)
        return self._storage.incr(normalized_key)

    def setex(self, key: str, seconds: int, value: Any) -> None:
        """값을 저장하면서 TTL도 함께 설정한다."""
        normalized_key = self._normalize_key(key)
        self._ensure_json_serializable(value)
        self._storage.setex(normalized_key, seconds, value)

    @staticmethod
    def _normalize_key(key: str) -> str:
        """모든 key를 문자열로 통일한다."""
        return str(key)

    @staticmethod
    def _ensure_json_serializable(value: Any) -> None:
        """값이 JSON 저장 가능한 형태인지 검사한다."""
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise TypeError("value must be JSON-serializable") from exc
