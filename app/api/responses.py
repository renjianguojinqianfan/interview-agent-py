from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.domain.errors import ErrorCode


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
