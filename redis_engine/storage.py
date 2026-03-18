"""Mini Redis의 원시 저장소 상태를 담는 레이어.

이 파일은 store, expire_at, lock을 한곳에서 관리한다.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from typing import Any


Snapshot = tuple[dict[str, Any], dict[str, float]]


class MemoryStore:
    def __init__(
        self,
        initial_store: Mapping[str, Any] | None = None,
        initial_expire_at: Mapping[str, float] | None = None,
        on_change: Callable[[dict[str, Any], dict[str, float]], None] | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        # 실제 데이터가 들어가는 공간
        self.store: dict[str, Any] = dict(initial_store or {})
        # 각 key가 언제 만료되는지 저장하는 공간
        self.expire_at: dict[str, float] = dict(initial_expire_at or {})
        # 여러 요청이 동시에 와도 데이터가 꼬이지 않게 잠그는 도구
        self.lock = threading.RLock()
        self._lock = self.lock
        # 데이터가 바뀐 뒤 저장 함수 같은 것을 연결하고 싶을 때 쓴다.
        self._on_change = on_change
        # 현재 시간을 가져오는 함수. 테스트할 때 바꿔 끼우기 쉽도록 분리했다.
        self._time_fn = time_fn or time.time
        # 시작할 때 이미 만료된 데이터가 있으면 먼저 정리한다.
        self.cleanup_expired()

    def set(self, key: str, value: Any) -> None:
        with self.lock:
            # 새 값을 넣으면 기존 TTL은 없애서 일반 key로 만든다.
            self.store[key] = value
            self.expire_at.pop(key, None)
            snapshot = self._snapshot_locked()
        self._emit_change(snapshot)

    def get(self, key: str) -> Any | None:
        with self.lock:
            # 값을 읽기 전에 "이미 만료된 key인지" 먼저 확인한다.
            snapshot = self._expire_key_if_needed_locked(key)
            value = self.store.get(key)
        self._emit_change(snapshot)
        return value

    def delete(self, *keys: str) -> int:
        if not keys:
            return 0

        with self.lock:
            now = self._time_fn()
            removed = 0
            changed = False
            for key in keys:
                # 이미 만료된 key면 먼저 지워서 상태를 맞춘다.
                if self._expire_key_locked(key, now):
                    changed = True
                if key in self.store:
                    self.store.pop(key, None)
                    self.expire_at.pop(key, None)
                    removed += 1
                    changed = True
            snapshot = self._snapshot_locked() if changed else None
        self._emit_change(snapshot)
        return removed

    def exists(self, *keys: str) -> int:
        if not keys:
            return 0

        with self.lock:
            now = self._time_fn()
            count = 0
            changed = False
            for key in keys:
                # 존재 여부를 셀 때도 만료 검사를 먼저 해야 정확하다.
                if self._expire_key_locked(key, now):
                    changed = True
                if key in self.store:
                    count += 1
            snapshot = self._snapshot_locked() if changed else None
        self._emit_change(snapshot)
        return count

    def incr(self, key: str) -> int:
        with self.lock:
            # 숫자를 올리기 전에 만료된 key인지 먼저 확인한다.
            self._expire_key_if_needed_locked(key)
            current_value = self.store.get(key, 0)
            try:
                next_value = int(current_value) + 1
            except (TypeError, ValueError) as exc:
                # 숫자가 아닌 값은 1 증가시킬 수 없다.
                raise ValueError("value is not an integer") from exc

            self.store[key] = next_value
            snapshot = self._snapshot_locked()
        self._emit_change(snapshot)
        return next_value

    def setex(self, key: str, seconds: int, value: Any) -> None:
        if seconds <= 0:
            raise ValueError("TTL must be greater than zero")

        with self.lock:
            # 값 저장
            self.store[key] = value
            # "지금 시간 + seconds"를 만료 시각으로 기록
            self.expire_at[key] = self._time_fn() + seconds
            snapshot = self._snapshot_locked()
        self._emit_change(snapshot)

    def clear(self) -> None:
        with self.lock:
            # 데이터와 만료 시간 정보를 모두 초기화
            self.store.clear()
            self.expire_at.clear()
            snapshot = self._snapshot_locked()
        self._emit_change(snapshot)

    def snapshot(self) -> Snapshot:
        with self.lock:
            # 현재 상태를 복사해서 바깥으로 넘긴다.
            return self._snapshot_locked()

    def restore(
        self,
        store: Mapping[str, Any] | None = None,
        expire_at: Mapping[str, float] | None = None,
    ) -> None:
        with self.lock:
            # 기존 내용을 비우고 저장된 데이터로 다시 채운다.
            self.store.clear()
            self.store.update(store or {})
            self.expire_at.clear()
            self.expire_at.update(expire_at or {})
            # 복구했더라도 이미 시간 지난 데이터는 다시 지운다.
            self._purge_all_expired_locked()
            snapshot = self._snapshot_locked()
        self._emit_change(snapshot)

    def cleanup_expired(self) -> int:
        with self.lock:
            # 만료된 key들을 한 번에 정리한다.
            removed = self._purge_all_expired_locked()
            snapshot = self._snapshot_locked() if removed else None
        self._emit_change(snapshot)
        return removed

    def persist_now(self) -> None:
        callback = self._on_change
        if callback is None:
            return
        with self.lock:
            # 지금 상태를 복사해서 저장 콜백으로 넘긴다.
            snapshot = self._snapshot_locked()
        callback(*snapshot)

    def _expire_key_if_needed_locked(self, key: str) -> Snapshot | None:
        # key 하나만 보고 만료 시간이 지났으면 지운다.
        if self._expire_key_locked(key, self._time_fn()):
            return self._snapshot_locked()
        return None

    def _expire_key_locked(self, key: str, now: float) -> bool:
        expires_at = self.expire_at.get(key)
        if expires_at is None or expires_at > now:
            return False

        # 만료된 key는 데이터와 만료 시간 정보 둘 다 지운다.
        self.store.pop(key, None)
        self.expire_at.pop(key, None)
        return True

    def _purge_all_expired_locked(self) -> int:
        now = self._time_fn()
        # 만료 시간이 지난 key 이름만 먼저 모은다.
        expired_keys = [
            key for key, expires_at in self.expire_at.items() if expires_at <= now
        ]
        for key in expired_keys:
            self.store.pop(key, None)
            self.expire_at.pop(key, None)
        return len(expired_keys)

    def _snapshot_locked(self) -> Snapshot:
        # 원본 dict를 그대로 넘기면 바깥에서 실수로 바꿀 수 있어서 복사본을 만든다.
        return dict(self.store), dict(self.expire_at)

    def _emit_change(self, snapshot: Snapshot | None) -> None:
        callback = self._on_change
        if callback is None or snapshot is None:
            return
        # 데이터가 바뀌었을 때 저장 함수 같은 외부 동작을 호출한다.
        callback(*snapshot)


# Storage라는 이름으로 불러도 같은 클래스를 쓰게 해 둔다.
Storage = MemoryStore
