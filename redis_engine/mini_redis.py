"""Mini Redis의 가장 작은 핵심 엔진.

현재 이 파일은 메모리 저장, TTL, 저장/복구 연결까지 맡는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from redis_engine.commands import RedisCommands
from redis_engine.persistence import RedisPersistence
from redis_engine.storage import MemoryStore


class MiniRedis:
    """API 코드가 사용하게 될 Mini Redis 진입점 클래스.

    바깥에서는 이 클래스만 보고 get/set/delete/exists를 쓰면 된다.
    내부에서는 storage, commands, persistence가 각자 역할을 나눠서 처리한다.
    """

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
        # API에서 쓰는 명령 인터페이스는 commands 레이어가 맡는다.
        self._commands = RedisCommands(self._storage)
        # 아래 3개는 내부 상태를 바로 보고 싶을 때 쓰기 쉽도록 연결해 둔 참조다.
        self._store = self._storage.store
        self._expire_at = self._storage.expire_at
        self._lock = self._storage.lock

    def set(self, key: str, value: Any) -> None:
        """문자열 key에 JSON 저장 가능한 값을 넣는다."""
        self._commands.set(key, value)

    def get(self, key: str) -> Any | None:
        """key에 해당하는 값을 반환한다. 없으면 None을 돌려준다."""
        return self._commands.get(key)

    def delete(self, key: str) -> bool:
        """key를 삭제하고, 실제로 삭제했는지 여부를 반환한다."""
        return self._commands.delete(key)

    def exists(self, key: str) -> bool:
        """현재 저장소에 해당 key가 존재하는지 확인한다."""
        return self._commands.exists(key)

    def incr(self, key: str) -> int:
        """숫자 값을 1 증가시킨다.

        나중에 조회수, 좋아요 수 같은 기능에 바로 쓸 수 있다.
        """
        return self._commands.incr(key)

    def setex(self, key: str, seconds: int, value: Any) -> None:
        """값을 저장하면서 TTL도 함께 설정한다.

        지금 API 팀은 아직 기본 4개 인터페이스만 먼저 쓰지만,
        setex를 미리 유지해 두면 나중에 인증번호나 캐시에 쉽게 확장할 수 있다.
        """
        self._commands.setex(key, seconds, value)

    def clear(self) -> None:
        """저장된 모든 key를 비운다."""
        # 저장된 데이터와 만료 시간 정보를 전부 비운다.
        self._storage.clear()

    def save(self) -> None:
        """현재 상태를 바로 파일에 저장한다."""
        # 자동 저장이 연결돼 있어도 필요하면 수동 저장을 한 번 더 할 수 있다.
        self._storage.persist_now()


# 앱 전체에서 MiniRedis 인스턴스를 하나만 공유해서 쓰기 위한 변수다.
# FastAPI에서 요청마다 새로 만들지 않고, 한 번 만든 것을 계속 재사용할 수 있다.
_shared_instance: MiniRedis | None = None


def get_shared_redis(data_file: str | Path | None = "data/dump.json") -> MiniRedis:
    """앱 전체에서 공유할 MiniRedis 인스턴스를 반환한다.

    왜 필요한가?
    - 요청마다 MiniRedis를 새로 만들면 메모리 데이터가 계속 초기화될 수 있다.
    - 그래서 서버가 켜져 있는 동안은 하나의 인스턴스를 같이 쓰는 게 좋다.
    """
    global _shared_instance

    if _shared_instance is None:
        _shared_instance = MiniRedis(data_file=data_file)

    return _shared_instance
