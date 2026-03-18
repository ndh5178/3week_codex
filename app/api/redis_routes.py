from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.redis_service import (
    clear_values,
    delete_value,
    exists_value,
    get_value,
    incr_value,
    set_value,
    set_value_with_ttl,
)


router = APIRouter(prefix="/redis", tags=["redis"])


class RedisKeyPayload(BaseModel):
    key: str


class RedisSetPayload(RedisKeyPayload):
    value: Any


class RedisSetExPayload(RedisSetPayload):
    seconds: int = Field(gt=0)


@router.post("/set")
def set_value_route(payload: RedisSetPayload) -> dict[str, Any]:
    return set_value(payload.key, payload.value)


@router.get("/get")
def get_value_route(key: str = Query(...)) -> dict[str, Any]:
    return get_value(key)


@router.get("/exists")
def exists_value_route(key: str = Query(...)) -> dict[str, Any]:
    return exists_value(key)


@router.post("/delete")
def delete_value_route(payload: RedisKeyPayload) -> dict[str, Any]:
    return delete_value(payload.key)


@router.post("/incr")
def incr_value_route(payload: RedisKeyPayload) -> dict[str, Any]:
    try:
        return incr_value(payload.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/setex")
def set_value_with_ttl_route(payload: RedisSetExPayload) -> dict[str, Any]:
    try:
        return set_value_with_ttl(payload.key, payload.seconds, payload.value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/clear")
def clear_values_route() -> dict[str, bool]:
    return clear_values()
