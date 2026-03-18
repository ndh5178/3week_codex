"""Mini Redis의 실제 메모리 저장소다."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from typing import Any


Snapshot = tuple[dict[str, Any], dict[str, float]]


class MemoryStore:
    """메모리 안에서 key-value와 TTL을 직접 관리하는 클래스다."""

    def __init__(
        self,
        initial_store: Mapping[str, Any] | None = None,
        initial_expire_at: Mapping[str, float] | None = None,
        on_change: Callable[[dict[str, Any], dict[str, float]], None] | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self.store: dict[str, Any] = dict(initial_store or {})
        self.expire_at: dict[str, float] = dict(initial_expire_at or {})
        self.lock = threading.RLock()
        self._lock = self.lock
        self._on_change = on_change
        self._time_fn = time_fn or time.time
        self.cleanup_expired()

    def set(self, key: str, value: Any) -> None:
        """값을 저장하고 기존 TTL은 제거한다."""
        with self.lock:
            self.store[key] = value
            self.expire_at.pop(key, None)
            snapshot = self._snapshot_locked()
        self._emit_change(snapshot)

    def get(self, key: str) -> Any | None:
        """값을 읽기 전에 먼저 만료 여부를 검사한다."""
        with self.lock:
            snapshot = self._expire_key_if_needed_locked(key)
            value = self.store.get(key)
        self._emit_change(snapshot)
        return value

    def delete(self, *keys: str) -> int:
        """하나 이상의 key를 삭제하고, 삭제된 개수를 반환한다."""
        if not keys:
            return 0

        with self.lock:
            now = self._time_fn()
            removed = 0
            changed = False

            for key in keys:
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
        """존재하는 key 개수를 반환한다."""
        if not keys:
            return 0

        with self.lock:
            now = self._time_fn()
            count = 0
            changed = False

            for key in keys:
                if self._expire_key_locked(key, now):
                    changed = True
                if key in self.store:
                    count += 1

            snapshot = self._snapshot_locked() if changed else None
        self._emit_change(snapshot)
        return count

    def incr(self, key: str) -> int:
        """숫자 값을 1 증가시킨다."""
        with self.lock:
            self._expire_key_if_needed_locked(key)
            current_value = self.store.get(key, 0)

            try:
                next_value = int(current_value) + 1
            except (TypeError, ValueError) as exc:
                raise ValueError("value is not an integer") from exc

            self.store[key] = next_value
            snapshot = self._snapshot_locked()
        self._emit_change(snapshot)
        return next_value

    def setex(self, key: str, seconds: int, value: Any) -> None:
        """값을 저장하면서 TTL도 설정한다."""
        if seconds <= 0:
            raise ValueError("TTL must be greater than zero")

        with self.lock:
            self.store[key] = value
            self.expire_at[key] = self._time_fn() + seconds
            snapshot = self._snapshot_locked()
        self._emit_change(snapshot)

    def clear(self) -> None:
        """모든 데이터와 TTL 정보를 비운다."""
        with self.lock:
            self.store.clear()
            self.expire_at.clear()
            snapshot = self._snapshot_locked()
        self._emit_change(snapshot)

    def snapshot(self) -> Snapshot:
        """현재 상태를 복사본으로 꺼낸다."""
        with self.lock:
            return self._snapshot_locked()

    def restore(
        self,
        store: Mapping[str, Any] | None = None,
        expire_at: Mapping[str, float] | None = None,
    ) -> None:
        """파일에서 읽은 상태로 메모리를 복구한다."""
        with self.lock:
            self.store.clear()
            self.store.update(store or {})
            self.expire_at.clear()
            self.expire_at.update(expire_at or {})
            self._purge_all_expired_locked()
            snapshot = self._snapshot_locked()
        self._emit_change(snapshot)

    def cleanup_expired(self) -> int:
        """이미 만료된 key들을 한꺼번에 정리한다."""
        with self.lock:
            removed = self._purge_all_expired_locked()
            snapshot = self._snapshot_locked() if removed else None
        self._emit_change(snapshot)
        return removed

    def persist_now(self) -> None:
        """현재 상태를 즉시 저장 콜백으로 넘긴다."""
        callback = self._on_change
        if callback is None:
            return

        with self.lock:
            snapshot = self._snapshot_locked()
        callback(*snapshot)

    def _expire_key_if_needed_locked(self, key: str) -> Snapshot | None:
        """특정 key가 만료됐으면 즉시 지운다."""
        if self._expire_key_locked(key, self._time_fn()):
            return self._snapshot_locked()
        return None

    def _expire_key_locked(self, key: str, now: float) -> bool:
        """현재 시각 기준으로 특정 key 만료 여부를 검사한다."""
        expires_at = self.expire_at.get(key)
        if expires_at is None or expires_at > now:
            return False

        self.store.pop(key, None)
        self.expire_at.pop(key, None)
        return True

    def _purge_all_expired_locked(self) -> int:
        """만료된 모든 key를 찾아 삭제한다."""
        now = self._time_fn()
        expired_keys = [
            key for key, expires_at in self.expire_at.items() if expires_at <= now
        ]

        for key in expired_keys:
            self.store.pop(key, None)
            self.expire_at.pop(key, None)

        return len(expired_keys)

    def _snapshot_locked(self) -> Snapshot:
        """현재 상태를 복사본으로 만든다."""
        return dict(self.store), dict(self.expire_at)

    def _emit_change(self, snapshot: Snapshot | None) -> None:
        """데이터가 바뀌었을 때 저장 콜백을 호출한다."""
        callback = self._on_change
        if callback is None or snapshot is None:
            return
        callback(*snapshot)


Storage = MemoryStore
