"""Mini Redis 저장/복구 레이어.

이 파일은 프로그램이 꺼져도 데이터를 다시 살릴 수 있게 만드는 부분이다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class RedisPersistence:
    """메모리 상태를 JSON 파일에 저장하고 다시 읽어오는 클래스."""

    def __init__(self, file_path: str | Path) -> None:
        # Path로 바꿔두면 폴더 생성, 파일 읽기/쓰기가 편하다.
        self.file_path = Path(file_path)

    def save(self, store: Mapping[str, Any], expire_at: Mapping[str, float]) -> None:
        """현재 메모리 상태를 파일에 저장한다."""
        # 저장할 폴더가 없으면 먼저 만든다.
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        # JSON으로 저장할 수 있게 평범한 dict 형태로 바꾼다.
        payload = {
            "store": dict(store),
            "expire_at": dict(expire_at),
        }

        # 한글도 깨지지 않게 UTF-8로 저장한다.
        self.file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> tuple[dict[str, Any], dict[str, float]]:
        """파일을 읽어서 store와 expire_at을 복구한다."""
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
                        # 잘못된 만료 시간 값은 무시하고 넘어간다.
                        continue

            return store, expire_at
        except (OSError, json.JSONDecodeError):
            # 파일이 깨졌거나 읽기에 실패해도 프로그램이 바로 죽지 않게 한다.
            return {}, {}
