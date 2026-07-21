"""AI 服务异常分类器测试（migration-plan 8.6：AI 异常 7001-7005 细分）。"""

import httpx
import openai

from app.domain.errors import ErrorCode
from app.infrastructure.ai.ai_error import classify_ai_error

_REQ = httpx.Request("POST", "https://dashscope.example/api")


def _resp(status: int) -> httpx.Response:
    return httpx.Response(status, request=_REQ)


class TestClassifyAiError:
    def test_stdlib_timeout_maps_to_timeout(self) -> None:
        assert classify_ai_error(TimeoutError()) is ErrorCode.AI_SERVICE_TIMEOUT

    def test_api_timeout_maps_to_timeout(self) -> None:
        assert classify_ai_error(openai.APITimeoutError(request=_REQ)) is ErrorCode.AI_SERVICE_TIMEOUT

    def test_rate_limit_maps_to_rate_limit(self) -> None:
        exc = openai.RateLimitError("rate", response=_resp(429), body=None)
        assert classify_ai_error(exc) is ErrorCode.AI_RATE_LIMIT_EXCEEDED

    def test_authentication_maps_to_key_invalid(self) -> None:
        exc = openai.AuthenticationError("auth", response=_resp(401), body=None)
        assert classify_ai_error(exc) is ErrorCode.AI_API_KEY_INVALID

    def test_permission_denied_maps_to_key_invalid(self) -> None:
        exc = openai.PermissionDeniedError("perm", response=_resp(403), body=None)
        assert classify_ai_error(exc) is ErrorCode.AI_API_KEY_INVALID

    def test_connection_maps_to_unavailable(self) -> None:
        exc = openai.APIConnectionError(message="conn", request=_REQ)
        assert classify_ai_error(exc) is ErrorCode.AI_SERVICE_UNAVAILABLE

    def test_other_openai_error_maps_to_generic(self) -> None:
        exc = openai.APIError("boom", _REQ, body=None)
        assert classify_ai_error(exc) is ErrorCode.AI_SERVICE_ERROR

    def test_unrecognized_returns_none(self) -> None:
        # 非 AI SDK 异常返回 None，由调用方决定兜底错误码（保持既有 caller-fallback 契约）
        assert classify_ai_error(RuntimeError("network")) is None
        assert classify_ai_error(Exception("x")) is None
        assert classify_ai_error(ValueError("bad")) is None
