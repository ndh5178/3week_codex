from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from redis_engine.storage import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def test_setex_expires_value_on_access(self) -> None:
        now = [1000.0]
        store = MemoryStore(time_fn=lambda: now[0])

        store.setex("post:1", 5, {"id": 1, "title": "cached"})
        self.assertEqual(store.get("post:1"), {"id": 1, "title": "cached"})

        now[0] = 1006.0

        self.assertIsNone(store.get("post:1"))
        self.assertEqual(store.exists("post:1"), 0)
        self.assertEqual(store.ttl("post:1"), -2)

    def test_set_clears_existing_ttl(self) -> None:
        now = [2000.0]
        store = MemoryStore(time_fn=lambda: now[0])

        store.setex("session:token", 5, {"username": "alice"})
        store.set("session:token", {"username": "bob"})

        now[0] = 3000.0

        self.assertEqual(store.get("session:token"), {"username": "bob"})
        self.assertEqual(store.ttl("session:token"), -1)

    def test_incr_rejects_non_integer_value(self) -> None:
        store = MemoryStore()
        store.set("views:post:1", "not-a-number")

        with self.assertRaises(ValueError):
            store.incr("views:post:1")


if __name__ == "__main__":
    unittest.main()
