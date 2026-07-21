from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.responses import Result
from app.domain.errors import ErrorCode

_FORWARD_HEADERS = ("X-Forwarded-For", "X-Real-IP", "Proxy-Client-IP")


def client_ip(request: Request) -> str:
    """限流 IP 维度键：按 X-Forwarded-For -> X-Real-IP -> Proxy-Client-IP -> remote_addr 回退。

    X-Forwarded-For 可能是逗号分隔的代理链，取最左（最初客户端）IP。对应 migration-plan 8.2。
    注意：转发头由客户端可控，仅在受信网关/代理之后可信（部署假设见 ADR-0007）。
    """
    for header in _FORWARD_HEADERS:
        value = request.headers.get(header)
        if value:
            candidate = value.split(",")[0].strip()
            if candidate:
                return candidate
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip)


def global_key(request: Request) -> str:  # noqa: ARG001  slowapi 按参数名注入
    """全局维度的限流键：所有请求共享同一计数桶。"""
    return "global"


async def rate_limit_exceeded_handler(_request: Request, _exc: RateLimitExceeded) -> JSONResponse:
    result = Result.error(ErrorCode.RATE_LIMIT_EXCEEDED)
    return JSONResponse(status_code=200, content=result.model_dump())
