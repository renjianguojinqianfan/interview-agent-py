from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel

from app.domain.errors import ErrorCode


def _strip_tz_iso(value: datetime) -> str:
    """ADR-0013：对外剥掉时区偏移，输出无偏移 ISO 串（与复用的 Java 前端契约一致）。"""
    return value.replace(tzinfo=None).isoformat()


# datetime 字段统一用此别名：内部 aware UTC，序列化时剥偏移。
NaiveIsoDatetime = Annotated[datetime, PlainSerializer(_strip_tz_iso, return_type=str)]


class BaseSchema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Result[T](BaseSchema):
    code: int
    message: str
    data: T | None = None

    @classmethod
    def success(cls, data: T | None = None) -> "Result[T]":
        return cls(code=200, message="success", data=data)

    @classmethod
    def error(cls, error_code: ErrorCode, message: str | None = None) -> "Result[None]":
        return Result[None](code=error_code.code, message=message or error_code.message, data=None)
