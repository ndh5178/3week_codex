"""Mini Redis의 가장 작은 핵심 엔진.

현재 이 파일은 "메모리에 key-value를 저장하는 기능"만 담당한다.
즉, Redis를 아주 단순화한 1단계 버전이라고 보면 된다.

나중에 프로젝트가 커지면 아래 역할들이 다른 파일로 분리될 수 있다.
- storage.py: store, expire_at, lock 같은 원시 저장소 상태
- commands.py: SET, GET, DEL, INCR, SETEX 같은 명령 처리
- persistence.py: dump.json 저장/복구
"""

from __future__ import annotations

from threading import RLock
from typing import Any


class MiniRedis:
    """메모리 안에서 key-value를 다루는 가장 단순한 Redis 클래스."""

    def __init__(self) -> None:
        # 실제 데이터가 들어가는 메모리 저장소다.
        self._store: dict[str, Any] = {}
        # 여러 요청이 동시에 들어와도 데이터가 꼬이지 않도록 보호한다.
        self._lock = RLock()

    def set(self, key: str, value: Any) -> None:
        """주어진 key에 값을 저장한다. 이미 있으면 덮어쓴다."""
        with self._lock:
            self._store[key] = value

    def get(self, key: str) -> Any | None:
        """key에 해당하는 값을 반환한다. 없으면 None을 돌려준다."""
        with self._lock:
            return self._store.get(key)

    def delete(self, key: str) -> bool:
        """key를 삭제하고, 실제로 삭제했는지 여부를 반환한다."""
        with self._lock:
            if key not in self._store:
                return False

            del self._store[key]
            return True

    def exists(self, key: str) -> bool:
        """현재 저장소에 해당 key가 존재하는지 확인한다."""
        with self._lock:
            return key in self._store

    def clear(self) -> None:
        """저장된 모든 key를 비운다."""
        with self._lock:
            self._store.clear()
