from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Protocol

from app.core.config import get_settings


PostRecord = dict[str, Any]
DEFAULT_AUTHOR = "익명"


class PostsRepository(Protocol):
    def list_posts(self) -> list[PostRecord]:
        ...

    def get_post(self, post_id: int) -> PostRecord | None:
        ...

    def create_post(self, payload: dict[str, Any]) -> PostRecord:
        ...

    def update_post(self, post_id: int, payload: dict[str, Any]) -> PostRecord | None:
        ...

    def reset(self) -> None:
        ...

    def count(self) -> int:
        ...


def _normalize_post_payload(
    payload: dict[str, Any],
    *,
    post_id: int | None = None,
) -> PostRecord:
    normalized = {
        "title": str(payload.get("title", "")).strip(),
        "content": str(payload.get("content", "")).strip(),
        "author": str(payload.get("author", "")).strip() or DEFAULT_AUTHOR,
    }
    if post_id is not None:
        normalized["id"] = int(post_id)
    return normalized


def load_seed_posts(seed_file: Path) -> list[PostRecord]:
    if not seed_file.exists():
        return []

    try:
        payload = json.loads(seed_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    raw_posts = payload.get("posts", [])
    if not isinstance(raw_posts, list):
        return []

    posts: list[PostRecord] = []
    for raw_post in raw_posts:
        if not isinstance(raw_post, dict):
            continue

        try:
            post_id = int(raw_post["id"])
        except (KeyError, TypeError, ValueError):
            continue

        posts.append(_normalize_post_payload(raw_post, post_id=post_id))

    return posts


@dataclass
class JsonPostsRepository:
    data_file: Path
    seed_file: Path
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def list_posts(self) -> list[PostRecord]:
        return self._load_posts()

    def get_post(self, post_id: int) -> PostRecord | None:
        for post in self._load_posts():
            if int(post["id"]) == post_id:
                return post
        return None

    def create_post(self, payload: dict[str, Any]) -> PostRecord:
        with self._lock:
            posts = self._load_posts()
            next_post_id = max((int(post["id"]) for post in posts), default=0) + 1
            new_post = _normalize_post_payload(payload, post_id=next_post_id)
            posts.append(new_post)
            self._write_posts(posts)
        return new_post

    def update_post(self, post_id: int, payload: dict[str, Any]) -> PostRecord | None:
        with self._lock:
            posts = self._load_posts()
            updated_post: PostRecord | None = None

            for index, post in enumerate(posts):
                if int(post["id"]) != post_id:
                    continue

                updated_post = _normalize_post_payload(
                    {
                        "title": payload.get("title", post["title"]),
                        "content": payload.get("content", post["content"]),
                        "author": payload.get("author", post["author"]),
                    },
                    post_id=post_id,
                )
                posts[index] = updated_post
                break

            if updated_post is None:
                return None

            self._write_posts(posts)
        return updated_post

    def reset(self) -> None:
        with self._lock:
            self._write_posts(load_seed_posts(self.seed_file))

    def count(self) -> int:
        return len(self._load_posts())

    def _ensure_data_file(self) -> None:
        if self.data_file.exists():
            return
        self._write_posts(load_seed_posts(self.seed_file))

    def _load_posts(self) -> list[PostRecord]:
        with self._lock:
            self._ensure_data_file()
            try:
                payload = json.loads(self.data_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return []

        raw_posts = payload.get("posts", [])
        if not isinstance(raw_posts, list):
            return []

        posts: list[PostRecord] = []
        for raw_post in raw_posts:
            if not isinstance(raw_post, dict):
                continue

            try:
                post_id = int(raw_post["id"])
            except (KeyError, TypeError, ValueError):
                continue

            posts.append(_normalize_post_payload(raw_post, post_id=post_id))

        return posts

    def _write_posts(self, posts: list[PostRecord]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text(
            json.dumps({"posts": posts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


@dataclass
class SqlitePostsRepository:
    db_path: Path
    seed_file: Path
    connect_timeout: float = 3.0
    seed_on_prepare: bool = True
    _prepare_lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _write_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _prepared: bool = field(default=False, init=False, repr=False)

    def list_posts(self) -> list[PostRecord]:
        self.prepare()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, content, author
                FROM posts
                ORDER BY id ASC
                """
            ).fetchall()
        return [self._row_to_post(row) for row in rows]

    def get_post(self, post_id: int) -> PostRecord | None:
        self.prepare()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, content, author
                FROM posts
                WHERE id = ?
                """,
                (post_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_post(row)

    def create_post(self, payload: dict[str, Any]) -> PostRecord:
        self.prepare()
        normalized = _normalize_post_payload(payload)
        with self._write_lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO posts (title, content, author)
                    VALUES (?, ?, ?)
                    """,
                    (
                        normalized["title"],
                        normalized["content"],
                        normalized["author"],
                    ),
                )
                post_id = int(cursor.lastrowid)
        created_post = self.get_post(post_id)
        if created_post is None:
            raise RuntimeError("failed to create post")
        return created_post

    def update_post(self, post_id: int, payload: dict[str, Any]) -> PostRecord | None:
        self.prepare()
        current_post = self.get_post(post_id)
        if current_post is None:
            return None

        normalized = _normalize_post_payload(
            {
                "title": payload.get("title", current_post["title"]),
                "content": payload.get("content", current_post["content"]),
                "author": payload.get("author", current_post["author"]),
            },
            post_id=post_id,
        )
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE posts
                    SET title = ?,
                        content = ?,
                        author = ?
                    WHERE id = ?
                    """,
                    (
                        normalized["title"],
                        normalized["content"],
                        normalized["author"],
                        post_id,
                    ),
                )
        return self.get_post(post_id)

    def reset(self) -> None:
        self.prepare()
        seed_posts = load_seed_posts(self.seed_file)
        with self._write_lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM posts")
                if seed_posts:
                    conn.executemany(
                        """
                        INSERT INTO posts (id, title, content, author)
                        VALUES (?, ?, ?, ?)
                        """,
                        [
                            (
                                int(post["id"]),
                                str(post["title"]),
                                str(post["content"]),
                                str(post["author"]),
                            )
                            for post in seed_posts
                        ],
                    )

    def count(self) -> int:
        self.prepare()
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM posts").fetchone()
        if row is None:
            return 0
        return int(row["count"])

    def prepare(self) -> None:
        if self._prepared:
            return

        with self._prepare_lock:
            if self._prepared:
                return

            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS posts (
                        id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        author TEXT NOT NULL
                    )
                    """
                )

                if self.seed_on_prepare:
                    row = conn.execute("SELECT COUNT(*) AS count FROM posts").fetchone()
                    existing_count = int(row["count"]) if row else 0
                    if existing_count == 0:
                        seed_posts = load_seed_posts(self.seed_file)
                        if seed_posts:
                            conn.executemany(
                                """
                                INSERT INTO posts (id, title, content, author)
                                VALUES (?, ?, ?, ?)
                                """,
                                [
                                    (
                                        int(post["id"]),
                                        str(post["title"]),
                                        str(post["content"]),
                                        str(post["author"]),
                                    )
                                    for post in seed_posts
                                ],
                            )

            self._prepared = True

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.connect_timeout,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_post(row: sqlite3.Row) -> PostRecord:
        return _normalize_post_payload(dict(row), post_id=int(row["id"]))


@dataclass
class PostgresPostsRepository:
    dsn: str
    seed_file: Path
    connect_timeout: int = 3
    seed_on_prepare: bool = True
    _prepare_lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _prepared: bool = field(default=False, init=False, repr=False)

    def list_posts(self) -> list[PostRecord]:
        self.prepare()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, content, author
                FROM posts
                ORDER BY id ASC
                """
            )
            rows = cur.fetchall()
        return [self._row_to_post(row) for row in rows]

    def get_post(self, post_id: int) -> PostRecord | None:
        self.prepare()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, content, author
                FROM posts
                WHERE id = %s
                """,
                (post_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_post(row)

    def create_post(self, payload: dict[str, Any]) -> PostRecord:
        self.prepare()
        normalized = _normalize_post_payload(payload)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO posts (title, content, author)
                VALUES (%s, %s, %s)
                RETURNING id, title, content, author
                """,
                (
                    normalized["title"],
                    normalized["content"],
                    normalized["author"],
                ),
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError("failed to create post")
        return self._row_to_post(row)

    def update_post(self, post_id: int, payload: dict[str, Any]) -> PostRecord | None:
        self.prepare()
        current_post = self.get_post(post_id)
        if current_post is None:
            return None

        normalized = _normalize_post_payload(
            {
                "title": payload.get("title", current_post["title"]),
                "content": payload.get("content", current_post["content"]),
                "author": payload.get("author", current_post["author"]),
            }
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE posts
                SET title = %s,
                    content = %s,
                    author = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, title, content, author
                """,
                (
                    normalized["title"],
                    normalized["content"],
                    normalized["author"],
                    post_id,
                ),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_post(row)

    def reset(self) -> None:
        self.prepare()
        seed_posts = load_seed_posts(self.seed_file)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE posts RESTART IDENTITY")
            if seed_posts:
                cur.executemany(
                    """
                    INSERT INTO posts (id, title, content, author)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [
                        (
                            int(post["id"]),
                            str(post["title"]),
                            str(post["content"]),
                            str(post["author"]),
                        )
                        for post in seed_posts
                    ],
                )
                self._sync_identity(cur)

    def count(self) -> int:
        self.prepare()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM posts")
            row = cur.fetchone()
        return int(row["count"]) if row else 0

    def prepare(self) -> None:
        if self._prepared:
            return

        with self._prepare_lock:
            if self._prepared:
                return

            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS posts (
                        id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        author TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )

                if self.seed_on_prepare:
                    cur.execute("SELECT COUNT(*) AS count FROM posts")
                    row = cur.fetchone()
                    existing_count = int(row["count"]) if row else 0
                    if existing_count == 0:
                        seed_posts = load_seed_posts(self.seed_file)
                        if seed_posts:
                            cur.executemany(
                                """
                                INSERT INTO posts (id, title, content, author)
                                VALUES (%s, %s, %s, %s)
                                """,
                                [
                                    (
                                        int(post["id"]),
                                        str(post["title"]),
                                        str(post["content"]),
                                        str(post["author"]),
                                    )
                                    for post in seed_posts
                                ],
                            )
                            self._sync_identity(cur)

            self._prepared = True

    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required for the PostgreSQL posts backend. "
                "Install `psycopg[binary]` first."
            ) from exc

        return psycopg.connect(
            self.dsn,
            connect_timeout=self.connect_timeout,
            row_factory=dict_row,
        )

    @staticmethod
    def _row_to_post(row: dict[str, Any]) -> PostRecord:
        return _normalize_post_payload(row, post_id=int(row["id"]))

    @staticmethod
    def _sync_identity(cur) -> None:  # type: ignore[no-untyped-def]
        cur.execute(
            """
            SELECT setval(
                pg_get_serial_sequence('posts', 'id'),
                COALESCE((SELECT MAX(id) FROM posts), 1),
                (SELECT COUNT(*) FROM posts) > 0
            )
            """
        )


@lru_cache(maxsize=1)
def get_posts_repository() -> PostsRepository:
    settings = get_settings()

    if settings.posts_backend == "json":
        return JsonPostsRepository(
            data_file=settings.posts_json_path,
            seed_file=settings.posts_seed_file,
        )

    if settings.posts_backend == "sqlite":
        return SqlitePostsRepository(
            db_path=settings.posts_sqlite_path,
            seed_file=settings.posts_seed_file,
            connect_timeout=settings.sqlite_connect_timeout,
        )

    if settings.posts_backend == "postgres":
        return PostgresPostsRepository(
            dsn=settings.postgres_dsn,
            seed_file=settings.posts_seed_file,
            connect_timeout=settings.postgres_connect_timeout,
            seed_on_prepare=settings.postgres_seed_on_prepare,
        )

    raise ValueError(f"Unsupported POSTS_BACKEND: {settings.posts_backend}")


def reset_posts_repository_cache() -> None:
    get_posts_repository.cache_clear()
