"""Mini Redis 저장/복구 레이어.

이 파일은 프로그램이 꺼져도 데이터를 다시 살릴 수 있게 만드는 부분이다.

여기에 들어갈 대표 기능:
- dump.json 파일로 현재 store 저장
- 서버 시작 시 dump.json 읽어서 복구
- expire_at 정보도 함께 저장/복구

즉, 메모리 데이터와 디스크 파일 사이를 연결하는 역할이다.
"""

from __future__ import annotations

import json
from pathlib import Path

from redis_engine.storage import RedisStorage


class RedisPersistence:
    """RedisStorage를 파일에 저장하고 다시 읽어오는 도우미 클래스.

    실행 중에는 Redis가 메모리 안에서 빠르게 동작한다.
    하지만 프로그램이 꺼지면 메모리 데이터는 사라진다.
    그래서 이 클래스가 중간에서 파일 저장/복구를 맡는다.
    """

    def __init__(self, file_path: str | Path) -> None:
        # Path 객체로 바꿔두면 파일 경로를 다루기 편하다.
        self.file_path = Path(file_path)

    def save(self, storage: RedisStorage) -> None:
        """현재 메모리 상태를 JSON 파일로 저장한다."""
        # 저장할 폴더가 없으면 먼저 만든다.
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        # storage 안의 내용을 일반 dict 형태로 바꾼다.
        data = storage.to_dict()

        # 한글이 깨지지 않게 UTF-8로 저장하고, 보기 좋게 들여쓰기도 준다.
        self.file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> RedisStorage:
        """저장 파일을 읽어서 RedisStorage 객체로 복구한다.

        파일이 없거나 내용이 잘못되어 있으면 에러로 끝내지 않고
        그냥 빈 저장소로 시작하게 만든다.
        """
        if not self.file_path.exists():
            return RedisStorage()

        try:
            raw_text = self.file_path.read_text(encoding="utf-8")
            if not raw_text.strip():
                return RedisStorage()

            data = json.loads(raw_text)
            if not isinstance(data, dict):
                return RedisStorage()

            return RedisStorage.from_dict(data)
        except (OSError, json.JSONDecodeError):
            # 파일이 깨졌거나 읽기 실패 시에도 프로그램이 바로 죽지 않게 한다.
            return RedisStorage()
