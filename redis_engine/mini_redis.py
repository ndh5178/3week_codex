"""Mini Redis의 가장 작은 핵심 엔진.

현재 이 파일은 메모리 저장, TTL, 저장/복구 연결까지 맡는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from redis_engine.persistence import RedisPersistence
from redis_engine.storage import MemoryStore


class MiniRedis:
    """메모리 안에서 key-value를 다루는 가장 단순한 Redis 클래스."""

    def __init__(self, data_file: str | Path | None = "data/dump.json") -> None:
        # data_file이 있으면 시작할 때 파일에서 데이터를 불러온다.
        self._persistence = RedisPersistence(data_file) if data_file is not None else None
        initial_store: dict[str, Any] = {}
        initial_expire_at: dict[str, float] = {}
        on_change = None

        if self._persistence is not None:
            initial_store, initial_expire_at = self._persistence.load()
            # 값이 바뀔 때마다 save가 호출되도록 연결한다.
            on_change = self._persistence.save

        # 실제 데이터 저장과 TTL 관리는 MemoryStore에게 맡긴다.
        self._storage = MemoryStore(
            initial_store,
            initial_expire_at,
            on_change=on_change,
        )
        # 아래 3개는 내부 상태를 바로 보고 싶을 때 쓰기 쉽도록 연결해 둔 참조다.
        self._store = self._storage.store
        self._expire_at = self._storage.expire_at
        self._lock = self._storage.lock

    def set(self, key: str, value: Any) -> None:
        """주어진 key에 값을 저장한다. 이미 있으면 덮어쓴다."""
        # key 자리에 value를 저장한다. 이미 있으면 덮어쓴다.
        self._storage.set(key, value)

    def get(self, key: str) -> Any | None:
        """key에 해당하는 값을 반환한다. 없으면 None을 돌려준다."""
        # 값을 꺼내기 전에 만료 시간이 지났는지도 같이 확인한다.
        return self._storage.get(key)

    def delete(self, key: str) -> bool:
        """key를 삭제하고, 실제로 삭제했는지 여부를 반환한다."""
        # 실제 삭제 개수는 숫자로 오지만, 여기서는 성공/실패만 알려준다.
        return self._storage.delete(key) > 0

    def exists(self, key: str) -> bool:
        """현재 저장소에 해당 key가 존재하는지 확인한다."""
        # key가 있으면 True, 없으면 False를 돌려준다.
        return self._storage.exists(key) > 0

    def incr(self, key: str) -> int:
        """숫자 값을 1 증가시킨다."""
        # 숫자 값을 1 올린다. 값이 없으면 0에서 시작해 1이 된다.
        return self._storage.incr(key)

    def setex(self, key: str, seconds: int, value: Any) -> None:
        """값을 저장하면서 TTL도 함께 설정한다."""
        # 값을 저장하면서 "몇 초 뒤에 자동 삭제"할지도 같이 기록한다.
        self._storage.setex(key, seconds, value)

    def clear(self) -> None:
        """저장된 모든 key를 비운다."""
        # 저장된 데이터와 만료 시간 정보를 전부 비운다.
        self._storage.clear()

    def save(self) -> None:
        """현재 상태를 바로 파일에 저장한다."""
        # 자동 저장이 연결돼 있어도 필요하면 수동 저장을 한 번 더 할 수 있다.
        self._storage.persist_now()
