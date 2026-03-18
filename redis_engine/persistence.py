"""Mini Redis의 저장/복구 레이어다."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class RedisPersistence:
    """메모리 상태를 JSON 파일로 저장하고 다시 읽는 클래스다."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def save(self, store: Mapping[str, Any], expire_at: Mapping[str, float]) -> None:
        """현재 메모리 상태를 파일로 저장한다."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "store": dict(store),
            "expire_at": dict(expire_at),
        }

        self.file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> tuple[dict[str, Any], dict[str, float]]:
        """파일에서 store와 expire_at을 읽어 복구한다."""
        if not self.file_path.exists():
            return {}, {}

        try:
            raw_text = self.file_path.read_text(encoding="utf-8")
            if not raw_text.strip():
                return {}, {}

            payload = json.loads(raw_text)
            if not isinstance(payload, dict):
                return {}, {}

            raw_store = payload.get("store", {})
            raw_expire_at = payload.get("expire_at", {})

            store = dict(raw_store) if isinstance(raw_store, dict) else {}
            expire_at: dict[str, float] = {}

            if isinstance(raw_expire_at, dict):
                for key, value in raw_expire_at.items():
                    try:
                        expire_at[str(key)] = float(value)
                    except (TypeError, ValueError):
                        continue

            return store, expire_at
        except (OSError, json.JSONDecodeError):
            return {}, {}
