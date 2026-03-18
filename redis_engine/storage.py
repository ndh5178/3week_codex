"""Mini Redis의 원시 저장소 상태를 담는 레이어.

이 파일은 앞으로 아래와 같은 상태를 분리해 둘 때 쓰기 좋다.
- store: 실제 key-value 데이터
- expire_at: TTL 만료 시간 정보
- lock: 동시 접근 보호

현재는 mini_redis.py 안에 이 상태가 함께 들어가 있지만,
구조를 더 깔끔하게 만들고 싶을 때 이 파일로 분리할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any


@dataclass
class RedisStorage:
    """Mini Redis가 실제로 들고 있는 메모리 상태 묶음.

    쉽게 말하면 이 클래스는
    "지금 Redis 안에 어떤 데이터가 들어 있는지"
    한곳에 모아두는 상자라고 생각하면 된다.
    """

    # 실제 key-value 데이터가 들어가는 공간이다.
    # 예:
    # {
    #   "session:abc123": "donghyun",
    #   "views:post:1": 132
    # }
    store: dict[str, Any] = field(default_factory=dict)

    # TTL(만료 시간)을 저장하는 공간이다.
    # 값은 "몇 시에 만료되는지"를 나타내는 숫자 시간(time.time())이다.
    # 예:
    # {
    #   "session:abc123": 1773810000.5
    # }
    expire_at: dict[str, float] = field(default_factory=dict)

    # 여러 요청이 동시에 들어와도 데이터가 꼬이지 않게 보호하는 자물쇠다.
    lock: RLock = field(default_factory=RLock)

    def clear(self) -> None:
        """메모리 안의 데이터와 TTL 정보를 모두 비운다."""
        with self.lock:
            self.store.clear()
            self.expire_at.clear()

    def to_dict(self) -> dict[str, Any]:
        """현재 메모리 상태를 파일 저장용 dict 형태로 바꾼다.

        JSON 파일로 저장하려면 클래스 자체를 그대로 저장하는 게 아니라,
        이런 식으로 평범한 dict 형태로 바꿔주는 과정이 필요하다.
        """
        with self.lock:
            return {
                "store": dict(self.store),
                "expire_at": dict(self.expire_at),
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RedisStorage":
        """파일에서 읽은 dict 데이터를 RedisStorage 객체로 바꾼다."""
        storage = cls()

        # 저장 파일이 비정상적이어도 최소한 빈 dict로 안전하게 시작한다.
        raw_store = data.get("store", {})
        raw_expire_at = data.get("expire_at", {})

        if isinstance(raw_store, dict):
            storage.store = dict(raw_store)

        if isinstance(raw_expire_at, dict):
            # expire_at 값은 시간 숫자(float)여야 하므로 가능한 경우 변환한다.
            cleaned_expire_at: dict[str, float] = {}
            for key, value in raw_expire_at.items():
                try:
                    cleaned_expire_at[str(key)] = float(value)
                except (TypeError, ValueError):
                    # 잘못된 값은 무시하고 넘어간다.
                    continue
            storage.expire_at = cleaned_expire_at

        return storage
