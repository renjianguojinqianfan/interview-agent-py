from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.responses import Result
from app.domain.errors import ErrorCode

limiter = Limiter(key_func=get_remote_address)


def global_key(request: Request) -> str:  # noqa: ARG001  slowapi 按参数名注入
    """全局维度的限流键：所有请求共享同一计数桶。"""
    return "global"


async def rate_limit_exceeded_handler(_request: Request, _exc: RateLimitExceeded) -> JSONResponse:
    result = Result.error(ErrorCode.RATE_LIMIT_EXCEEDED)
    return JSONResponse(status_code=200, content=result.model_dump())
