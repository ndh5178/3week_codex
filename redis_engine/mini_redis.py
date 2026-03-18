
from __future__ import annotations

from threading import RLock
from typing import Any


class MiniRedis:
    """Simple in-memory key-value store used as the project cache engine."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._lock = RLock()

    def set(self, key: str, value: Any) -> None:
        """Store or overwrite a value by key."""
        with self._lock:
            self._store[key] = value

    def get(self, key: str) -> Any | None:
        """Return the stored value, or None when the key does not exist."""
        with self._lock:
            return self._store.get(key)

    def delete(self, key: str) -> bool:
        """Delete a key and return whether anything was removed."""
        with self._lock:
            if key not in self._store:
                return False

            del self._store[key]
            return True

    def exists(self, key: str) -> bool:
        """Check whether a key exists in the store."""
        with self._lock:
            return key in self._store

    def clear(self) -> None:
        """Remove all keys from the store."""
        with self._lock:
            self._store.clear()
