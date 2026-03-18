from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from redis_engine.mini_redis import MiniRedis


class MiniRedisPersistenceTests(unittest.TestCase):
    def test_set_writes_dump_and_restore_reads_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dump_path = Path(temp_dir) / "redis_dump.json"

            redis = MiniRedis(data_file=dump_path)
            redis.set("session:abc", {"username": "alice"})

            payload = json.loads(dump_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["store"]["session:abc"]["username"], "alice")
            self.assertEqual(payload["expire_at"], {})

            reloaded = MiniRedis(data_file=dump_path)
            self.assertEqual(reloaded.get("session:abc"), {"username": "alice"})

    def test_setex_persists_expire_at_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dump_path = Path(temp_dir) / "redis_dump.json"

            redis = MiniRedis(data_file=dump_path)
            redis.setex("post:1", 10, {"id": 1, "title": "cached"})

            payload = json.loads(dump_path.read_text(encoding="utf-8"))
            self.assertIn("post:1", payload["store"])
            self.assertIn("post:1", payload["expire_at"])


if __name__ == "__main__":
    unittest.main()
