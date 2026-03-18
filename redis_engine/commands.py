"""Mini Redis 명령 처리 레이어.

이 파일은 API나 서비스 코드가 바로 storage 내부 구조를 건드리지 않도록
중간에서 명령을 정리해 주는 역할을 한다.

쉽게 말하면:
- storage.py 는 "데이터를 들고 있는 장소"
- commands.py 는 "그 데이터를 어떻게 다룰지 정한 규칙"

지금은 API 팀과 약속한 기본 인터페이스 4개를 중심으로 맞춘다.
- get(key) -> 없으면 None
- set(key, value) -> 저장
- delete(key) -> 삭제 성공 여부 bool
- exists(key) -> 존재 여부 bool

추가로 나중에 바로 확장할 수 있게 incr, setex도 함께 준비해 둔다.
"""

from __future__ import annotations

import json
from typing import Any

from redis_engine.storage import MemoryStore


class RedisCommands:
    """MemoryStore를 실제 Redis처럼 다루기 쉽게 감싸는 클래스."""

    def __init__(self, storage: MemoryStore) -> None:
        # 실제 데이터 저장은 storage가 맡고,
        # 이 클래스는 "어떤 규칙으로 호출할지"를 담당한다.
        self._storage = storage

    def get(self, key: str) -> Any | None:
        """문자열 key로 값을 읽는다. 없으면 None을 반환한다."""
        normalized_key = self._normalize_key(key)
        return self._storage.get(normalized_key)

    def set(self, key: str, value: Any) -> None:
        """문자열 key에 JSON 직렬화 가능한 값을 저장한다."""
        normalized_key = self._normalize_key(key)
        self._ensure_json_serializable(value)
        self._storage.set(normalized_key, value)

    def delete(self, key: str) -> bool:
        """삭제가 성공했는지 True/False로 반환한다."""
        normalized_key = self._normalize_key(key)
        return self._storage.delete(normalized_key) > 0

    def exists(self, key: str) -> bool:
        """해당 key가 존재하는지 True/False로 반환한다."""
        normalized_key = self._normalize_key(key)
        return self._storage.exists(normalized_key) > 0

    def incr(self, key: str) -> int:
        """숫자 값을 1 증가시킨다.

        이 기능은 조회수 카운터 같은 곳에 많이 쓰인다.
        """
        normalized_key = self._normalize_key(key)
        return self._storage.incr(normalized_key)

    def setex(self, key: str, seconds: int, value: Any) -> None:
        """값을 저장하면서 TTL(몇 초 뒤 삭제할지)도 함께 설정한다."""
        normalized_key = self._normalize_key(key)
        self._ensure_json_serializable(value)
        self._storage.setex(normalized_key, seconds, value)

    @staticmethod
    def _normalize_key(key: str) -> str:
        """key 규칙을 문자열로 통일한다.

        API 팀과 약속한 규칙이 "모든 key는 문자열" 이기 때문에,
        숫자나 다른 타입이 들어오면 문자열로 바꿔서 사용한다.
        예:
        - 1 -> "1"
        - "post:1" -> "post:1"
        """
        return str(key)

    @staticmethod
    def _ensure_json_serializable(value: Any) -> None:
        """값이 JSON 파일에 저장 가능한 형태인지 미리 확인한다.

        지금 프로젝트는 persistence.py에서 JSON 파일로 저장하므로,
        value도 JSON으로 바꿀 수 있는 값이어야 안전하다.

        예:
        - 가능: dict, list, str, int, float, bool, None
        - 어려움: 함수, 클래스 객체, 파일 핸들
        """
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise TypeError("value must be JSON-serializable") from exc
