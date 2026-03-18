"""Board API가 외부 Mini Redis 서버에 붙기 위한 클라이언트."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

import httpx

from redis_engine.mini_redis import get_shared_redis


class EmbeddedMiniRedisClient:
    """테스트나 로컬 폴백용으로 기존 MiniRedis 객체를 감싼다."""

    def __init__(self, data_file: str | Path | None = None) -> None:
        self._redis = get_shared_redis(data_file=data_file)

    def set(self, key: str, value: Any) -> None:
        self._redis.set(key, value)

    def get(self, key: str) -> Any | None:
        return self._redis.get(key)

    def delete(self, key: str) -> bool:
        return self._redis.delete(key)

    def exists(self, key: str) -> bool:
        return self._redis.exists(key)

    def incr(self, key: str) -> int:
        return self._redis.incr(key)

    def setex(self, key: str, seconds: int, value: Any) -> None:
        self._redis.setex(key, seconds, value)

    def ttl(self, key: str) -> int:
        return self._redis.ttl(key)

    def clear(self) -> None:
        self._redis.clear()


class RemoteMiniRedisClient:
    """별도 프로세스로 실행 중인 Mini Redis 서버에 HTTP로 붙는다."""

    def __init__(self, base_url: str, timeout_seconds: float = 3.0) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds)

    def set(self, key: str, value: Any) -> None:
        self._client.post("/redis/set", json={"key": str(key), "value": value}).raise_for_status()

    def get(self, key: str) -> Any | None:
        response = self._client.get("/redis/get", params={"key": str(key)})
        response.raise_for_status()
        return response.json().get("value")

    def delete(self, key: str) -> bool:
        response = self._client.post("/redis/delete", json={"key": str(key)})
        response.raise_for_status()
        return bool(response.json().get("deleted"))

    def exists(self, key: str) -> bool:
        response = self._client.get("/redis/exists", params={"key": str(key)})
        response.raise_for_status()
        return bool(response.json().get("exists"))

    def incr(self, key: str) -> int:
        response = self._client.post("/redis/incr", json={"key": str(key)})
        response.raise_for_status()
        return int(response.json().get("value", 0))

    def setex(self, key: str, seconds: int, value: Any) -> None:
        self._client.post(
            "/redis/setex",
            json={"key": str(key), "seconds": int(seconds), "value": value},
        ).raise_for_status()

    def ttl(self, key: str) -> int:
        response = self._client.get("/redis/ttl", params={"key": str(key)})
        response.raise_for_status()
        return int(response.json().get("ttl", -2))

    def clear(self) -> None:
        self._client.post("/redis/clear").raise_for_status()


_shared_clients: dict[str, Any] = {}
_shared_clients_lock = RLock()


def get_shared_redis_client(
    *,
    backend: str,
    base_url: str,
    timeout_seconds: float,
    data_file: str | Path | None,
) -> Any:
    shared_key = f"{backend}:{base_url}:{data_file}"

    with _shared_clients_lock:
        client = _shared_clients.get(shared_key)
        if client is not None:
            return client

        if backend == "embedded":
            client = EmbeddedMiniRedisClient(data_file=data_file)
        else:
            client = RemoteMiniRedisClient(base_url=base_url, timeout_seconds=timeout_seconds)

        _shared_clients[shared_key] = client
        return client

