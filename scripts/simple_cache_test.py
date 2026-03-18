from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
PYDEPS_DIR = ROOT_DIR / ".pydeps"

if str(PYDEPS_DIR) not in sys.path:
    sys.path.insert(0, str(PYDEPS_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.board_service import (
    get_post,
    reset_cache,
    reset_posts_store,
    update_post,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simple terminal checks for DB/cache behavior.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check",
        help="Show that the first read comes from DB and the second from cache.",
    )
    check_parser.add_argument("--post-id", type=int, default=1)

    update_parser = subparsers.add_parser(
        "update",
        help="Show cache invalidation after updating a post.",
    )
    update_parser.add_argument("--post-id", type=int, default=1)

    time_parser = subparsers.add_parser(
        "time",
        help="Measure DB read time vs cache read time.",
    )
    time_parser.add_argument("--post-id", type=int, default=1)
    time_parser.add_argument("--iterations", type=int, default=200)

    return parser.parse_args()


def print_json(label: str, payload: dict[str, Any] | None) -> None:
    print(label)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print()


def run_check(post_id: int) -> int:
    reset_cache()
    first = get_post(post_id)
    second = get_post(post_id)

    print_json("first call", first)
    print_json("second call", second)
    return 0


def run_update(post_id: int) -> int:
    try:
        reset_posts_store()
        reset_cache()
        before = get_post(post_id)
        cached = get_post(post_id)
        updated = update_post(
            post_id,
            {
                "title": "Updated title",
                "content": "Updated content",
                "author": "API Team",
            },
        )
        after_update = get_post(post_id)
        after_cache = get_post(post_id)

        print_json("before update", before)
        print_json("cached before update", cached)
        print_json("update result", updated)
        print_json("first read after update", after_update)
        print_json("second read after update", after_cache)
        return 0
    finally:
        reset_posts_store()
        reset_cache()


def run_time(post_id: int, iterations: int) -> int:
    db_timings: list[float] = []
    cache_timings: list[float] = []

    for _ in range(iterations):
        reset_cache()
        started = time.perf_counter()
        result = get_post(post_id)
        elapsed = time.perf_counter() - started
        if result is None or result.get("source") != "db":
            raise RuntimeError("DB timing test failed.")
        db_timings.append(elapsed)

    reset_cache()
    warmed = get_post(post_id)
    if warmed is None:
        raise RuntimeError(f"Post {post_id} was not found.")

    for _ in range(iterations):
        started = time.perf_counter()
        result = get_post(post_id)
        elapsed = time.perf_counter() - started
        if result is None or result.get("source") != "cache":
            raise RuntimeError("Cache timing test failed.")
        cache_timings.append(elapsed)

    db_avg_ms = statistics.mean(db_timings) * 1000
    cache_avg_ms = statistics.mean(cache_timings) * 1000
    speedup = db_avg_ms / cache_avg_ms if cache_avg_ms > 0 else float("inf")

    print(f"post id       : {post_id}")
    print(f"iterations    : {iterations}")
    print(f"DB average    : {db_avg_ms:.4f} ms")
    print(f"Cache average : {cache_avg_ms:.4f} ms")
    print(f"Speedup       : {speedup:.2f}x")
    return 0


def main() -> int:
    args = parse_args()

    if args.command == "check":
        return run_check(args.post_id)
    if args.command == "update":
        return run_update(args.post_id)
    if args.command == "time":
        return run_time(args.post_id, args.iterations)

    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
