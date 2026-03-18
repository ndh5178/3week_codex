from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from threading import Lock
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

    def delete_post(self, post_id: int) -> PostRecord | None:
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
class MongoPostsRepository:
    uri: str
    database_name: str
    collection_name: str
    seed_file: Path
    connect_timeout_ms: int = 3000
    seed_on_prepare: bool = True
    _prepare_lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _prepared: bool = field(default=False, init=False, repr=False)

    @property
    def counters_collection_name(self) -> str:
        return f"{self.collection_name}_counters"

    def list_posts(self) -> list[PostRecord]:
        self.prepare()
        rows = self._get_collection().find({}, {"_id": 0}).sort("id", 1)
        return [self._doc_to_post(row) for row in rows]

    def get_post(self, post_id: int) -> PostRecord | None:
        self.prepare()
        row = self._get_collection().find_one({"id": post_id}, {"_id": 0})
        if row is None:
            return None
        return self._doc_to_post(row)

    def create_post(self, payload: dict[str, Any]) -> PostRecord:
        self.prepare()
        next_post_id = self._next_post_id()
        new_post = _normalize_post_payload(payload, post_id=next_post_id)
        self._get_collection().insert_one(dict(new_post))
        return new_post

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

        row = self._get_collection().find_one_and_update(
            {"id": post_id},
            {"$set": dict(normalized)},
            return_document=self._get_return_document_after(),
            projection={"_id": 0},
        )
        if row is None:
            return None
        return self._doc_to_post(row)

    def delete_post(self, post_id: int) -> PostRecord | None:
        self.prepare()
        deleted_post = self.get_post(post_id)
        if deleted_post is None:
            return None

        self._get_collection().delete_one({"id": post_id})
        return deleted_post

    def reset(self) -> None:
        self.prepare()
        seed_posts = load_seed_posts(self.seed_file)
        self._get_collection().delete_many({})
        if seed_posts:
            self._get_collection().insert_many([dict(post) for post in seed_posts])

        max_post_id = max((int(post["id"]) for post in seed_posts), default=0)
        self._get_counters_collection().update_one(
            {"name": "posts"},
            {"$set": {"value": max_post_id}},
            upsert=True,
        )

    def count(self) -> int:
        self.prepare()
        return int(self._get_collection().count_documents({}))

    def prepare(self) -> None:
        if self._prepared:
            return

        with self._prepare_lock:
            if self._prepared:
                return

            collection = self._get_collection()
            collection.create_index("id", unique=True)

            if self.seed_on_prepare and collection.count_documents({}) == 0:
                seed_posts = load_seed_posts(self.seed_file)
                if seed_posts:
                    collection.insert_many([dict(post) for post in seed_posts])

                max_post_id = max((int(post["id"]) for post in seed_posts), default=0)
                self._get_counters_collection().update_one(
                    {"name": "posts"},
                    {"$set": {"value": max_post_id}},
                    upsert=True,
                )

            self._prepared = True

    def _next_post_id(self) -> int:
        row = self._get_counters_collection().find_one_and_update(
            {"name": "posts"},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=self._get_return_document_after(),
            projection={"_id": 0, "value": 1},
        )
        if row is None:
            return 1
        return int(row.get("value", 1))

    def _get_collection(self):
        return self._get_database()[self.collection_name]

    def _get_counters_collection(self):
        return self._get_database()[self.counters_collection_name]

    def _get_database(self):
        return self._connect()[self.database_name]

    def _connect(self):
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError(
                "pymongo is required for the MongoDB posts backend. Install `pymongo` first."
            ) from exc

        return MongoClient(
            self.uri,
            serverSelectionTimeoutMS=self.connect_timeout_ms,
            connectTimeoutMS=self.connect_timeout_ms,
        )

    @staticmethod
    def _get_return_document_after():
        from pymongo import ReturnDocument

        return ReturnDocument.AFTER

    @staticmethod
    def _doc_to_post(row: dict[str, Any]) -> PostRecord:
        normalized = dict(row)
        normalized.pop("_id", None)
        return _normalize_post_payload(normalized, post_id=int(normalized["id"]))


@lru_cache(maxsize=1)
def get_posts_repository() -> PostsRepository:
    settings = get_settings()
    return MongoPostsRepository(
        uri=settings.mongodb_uri,
        database_name=settings.mongodb_database,
        collection_name=settings.mongodb_collection,
        seed_file=settings.posts_seed_file,
        connect_timeout_ms=settings.mongodb_connect_timeout_ms,
        seed_on_prepare=settings.mongodb_seed_on_prepare,
    )


def reset_posts_repository_cache() -> None:
    get_posts_repository.cache_clear()
