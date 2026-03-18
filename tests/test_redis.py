from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from redis_engine.mini_redis import MiniRedis


def test_set_get_exists_and_delete_round_trip() -> None:
    redis = MiniRedis(data_file=None)

    redis.set("user:1", {"name": "alice"})

    assert redis.get("user:1") == {"name": "alice"}
    assert redis.exists("user:1") is True
    assert redis.delete("user:1") is True
    assert redis.get("user:1") is None
    assert redis.exists("user:1") is False


def test_keys_are_normalized_to_strings() -> None:
    redis = MiniRedis(data_file=None)

    redis.set(123, "normalized")

    assert redis.get("123") == "normalized"
    assert redis.exists(123) is True


def test_set_rejects_non_json_serializable_values() -> None:
    redis = MiniRedis(data_file=None)

    with pytest.raises(TypeError):
        redis.set("bad", object())


def test_setex_expires_values_after_ttl() -> None:
    redis = MiniRedis(data_file=None)
    current_time = {"now": 1000.0}
    redis._storage._time_fn = lambda: current_time["now"]  # type: ignore[attr-defined]

    redis.setex("session:alice", 5, {"user": "alice"})

    assert redis.get("session:alice") == {"user": "alice"}

    current_time["now"] += 6

    assert redis.get("session:alice") is None
    assert redis.exists("session:alice") is False


def test_incr_is_thread_safe() -> None:
    redis = MiniRedis(data_file=None)

    def worker(_: int) -> None:
        for _ in range(125):
            redis.incr("hits")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker, range(8)))

    assert redis.get("hits") == 1000


def test_incr_rejects_non_integer_values() -> None:
    redis = MiniRedis(data_file=None)
    redis.set("hits", "nope")

    with pytest.raises(ValueError):
        redis.incr("hits")


def test_clear_removes_all_keys() -> None:
    redis = MiniRedis(data_file=None)
    redis.set("a", 1)
    redis.set("b", 2)

    redis.clear()

    assert redis.get("a") is None
    assert redis.get("b") is None
    assert redis.exists("a") is False
    assert redis.exists("b") is False


def test_persistence_restores_saved_values(tmp_path: Path) -> None:
    dump_file = tmp_path / "redis_dump.json"
    writer = MiniRedis(data_file=dump_file)
    writer.set("name", "codex")
    writer.setex("session:1", 30, {"user": "alice"})

    reader = MiniRedis(data_file=dump_file)

    assert reader.get("name") == "codex"
    assert reader.get("session:1") == {"user": "alice"}


def test_expired_values_are_dropped_during_startup_load(tmp_path: Path) -> None:
    dump_file = tmp_path / "redis_dump.json"
    payload = {
        "store": {
            "expired": "old",
            "live": "fresh",
        },
        "expire_at": {
            "expired": time.time() - 10,
        },
    }
    dump_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    redis = MiniRedis(data_file=dump_file)

    assert redis.get("expired") is None
    assert redis.exists("expired") is False
    assert redis.get("live") == "fresh"
