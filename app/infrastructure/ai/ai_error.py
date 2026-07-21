"""AI 服务异常分类：将 LLM SDK 异常映射到 7001-7005 细分错误码。

对应 migration-plan 8.6：超时(7002)/握手失败(7001)/密钥无效(7004)/频率超限(7005)/其他(7003)。
仅在识别到明确的 AI SDK 异常类型时返回对应错误码；无法识别（非 AI SDK 异常）返回 None，
由调用方决定兜底错误码（保持 StructuredOutputInvoker 既有 caller-supplied error_code 契约）。
"""

import openai

from app.domain.errors import ErrorCode


def classify_ai_error(exc: BaseException) -> ErrorCode | None:
    """将 AI SDK 异常映射到 ErrorCode(7001-7005)；无法识别返回 None（调用方兜底）。

    注意 openai.APITimeoutError 是 APIConnectionError 的子类，故超时须先于连接判断。
    """
    if isinstance(exc, TimeoutError | openai.APITimeoutError):
        return ErrorCode.AI_SERVICE_TIMEOUT
    if isinstance(exc, openai.RateLimitError):
        return ErrorCode.AI_RATE_LIMIT_EXCEEDED
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return ErrorCode.AI_API_KEY_INVALID
    if isinstance(exc, openai.APIConnectionError):
        return ErrorCode.AI_SERVICE_UNAVAILABLE
    if isinstance(exc, openai.OpenAIError):
        return ErrorCode.AI_SERVICE_ERROR
    return None
