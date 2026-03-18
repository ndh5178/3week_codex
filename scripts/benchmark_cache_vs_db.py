from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient

from app.main import app
from app.services.board_service import get_post, reset_cache


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare fake DB access time against Mini Redis cache hits.",
    )
    parser.add_argument("--post-id", type=int, default=1, help="Post id to request.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=300,
        help="Number of timed requests for each path.",
    )
    parser.add_argument(
        "--mode",
        choices=("service", "api", "both"),
        default="both",
        help="Which layer to benchmark.",
    )
    return parser.parse_args()


def benchmark_service_layer(post_id: int, iterations: int) -> tuple[list[float], list[float]]:
    db_timings: list[float] = []
    cache_timings: list[float] = []

    # Warm up imports and function dispatch to reduce one-time overhead.
    reset_cache()
    get_post(post_id)

    for _ in range(iterations):
        reset_cache()
        started = time.perf_counter()
        response = get_post(post_id)
        db_timings.append(time.perf_counter() - started)
        if response is None or response.get("source") != "db":
            raise RuntimeError("Expected a DB-backed response during service benchmark.")

    reset_cache()
    warmed_response = get_post(post_id)
    if warmed_response is None:
        raise RuntimeError(f"Post {post_id} was not found.")

    for _ in range(iterations):
        started = time.perf_counter()
        response = get_post(post_id)
        cache_timings.append(time.perf_counter() - started)
        if response is None or response.get("source") != "cache":
            raise RuntimeError("Expected a cache-backed response during service benchmark.")

    return db_timings, cache_timings


def benchmark_api_layer(post_id: int, iterations: int) -> tuple[list[float], list[float]]:
    client = TestClient(app)
    db_timings: list[float] = []
    cache_timings: list[float] = []

    reset_cache()
    client.get(f"/posts/{post_id}")

    for _ in range(iterations):
        reset_cache()
        started = time.perf_counter()
        response = client.get(f"/posts/{post_id}")
        db_timings.append(time.perf_counter() - started)
        if response.status_code != 200 or response.json().get("source") != "db":
            raise RuntimeError("Expected a DB-backed response during API benchmark.")

    reset_cache()
    warmed_response = client.get(f"/posts/{post_id}")
    if warmed_response.status_code != 200:
        raise RuntimeError(f"Post {post_id} was not found.")

    for _ in range(iterations):
        started = time.perf_counter()
        response = client.get(f"/posts/{post_id}")
        cache_timings.append(time.perf_counter() - started)
        if response.status_code != 200 or response.json().get("source") != "cache":
            raise RuntimeError("Expected a cache-backed response during API benchmark.")

    return db_timings, cache_timings


def format_summary(name: str, db_timings: list[float], cache_timings: list[float]) -> str:
    db_avg_ms = statistics.mean(db_timings) * 1000
    cache_avg_ms = statistics.mean(cache_timings) * 1000
    db_median_ms = statistics.median(db_timings) * 1000
    cache_median_ms = statistics.median(cache_timings) * 1000
    speedup = db_avg_ms / cache_avg_ms if cache_avg_ms > 0 else float("inf")

    return "\n".join(
        [
            f"[{name}]",
            f"DB average    : {db_avg_ms:.4f} ms",
            f"Cache average : {cache_avg_ms:.4f} ms",
            f"DB median     : {db_median_ms:.4f} ms",
            f"Cache median  : {cache_median_ms:.4f} ms",
            f"Speedup       : {speedup:.2f}x",
        ]
    )


def main() -> int:
    args = parse_args()
    reports: list[str] = []

    if args.mode in {"service", "both"}:
        service_db_timings, service_cache_timings = benchmark_service_layer(
            args.post_id,
            args.iterations,
        )
        reports.append(
            format_summary(
                "service layer",
                service_db_timings,
                service_cache_timings,
            )
        )

    if args.mode in {"api", "both"}:
        api_db_timings, api_cache_timings = benchmark_api_layer(
            args.post_id,
            args.iterations,
        )
        reports.append(
            format_summary(
                "api layer",
                api_db_timings,
                api_cache_timings,
            )
        )

    print("\n\n".join(reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
