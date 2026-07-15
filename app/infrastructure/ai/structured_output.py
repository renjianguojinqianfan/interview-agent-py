import logging
from typing import TypeVar, cast

from json_repair import repair_json
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.ai.prompt_constants import ANTI_INJECTION_INSTRUCTION

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_STRICT_JSON_INSTRUCTION = """
请仅返回可被 JSON 解析器直接解析的 JSON 对象，并严格满足字段结构要求：
1) 不要输出 Markdown 代码块（如 ```json）。
2) 不要输出任何解释文字、前后缀、注释。
3) 所有字符串内引号必须正确转义。
"""

_ERROR_MESSAGE_MAX_LENGTH = 200


class _ParseError(Exception):
    """Internal exception for structured output JSON parse failures (tenacity-retryable)."""


class StructuredOutputInvoker:
    def __init__(self, max_attempts: int = 2) -> None:
        self._max_attempts = max(1, max_attempts)

    async def invoke(
        self,
        llm: ChatOpenAI,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
        error_code: ErrorCode,
        error_prefix: str,
        log_context: str,
    ) -> T:
        secured_system_prompt = system_prompt + ANTI_INJECTION_INSTRUCTION
        structured_llm = llm.with_structured_output(output_model, include_raw=True)

        last_error: Exception | None = None
        attempt_num = 0

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_attempts),
                retry=retry_if_exception_type(_ParseError),
            ):
                with attempt:
                    attempt_num += 1
                    attempt_prompt = (
                        secured_system_prompt
                        if attempt_num == 1
                        else self._build_retry_prompt(secured_system_prompt, last_error)
                    )
                    messages = [
                        SystemMessage(content=attempt_prompt),
                        HumanMessage(content=user_prompt),
                    ]

                    result = await structured_llm.ainvoke(messages)
                    parsed = result.get("parsed")
                    if parsed is not None:
                        return cast(T, parsed)

                    parsing_error = result.get("parsing_error")
                    raw = result.get("raw")
                    if raw is not None and parsing_error is not None:
                        repaired = self._try_repair_json(raw, output_model)
                        if repaired is not None:
                            logger.warning(
                                "%s 结构化 JSON 通过 json-repair 修复后解析成功",
                                log_context,
                            )
                            return repaired

                    err = parsing_error or Exception("Unknown parsing error")
                    last_error = err
                    if attempt_num < self._max_attempts:
                        logger.warning(
                            "%s 结构化解析失败，准备重试: attempt=%d/%d, error=%s",
                            log_context,
                            attempt_num,
                            self._max_attempts,
                            str(last_error),
                        )
                    else:
                        logger.error(
                            "%s 结构化解析失败，已达最大重试次数: attempts=%d, error=%s",
                            log_context,
                            self._max_attempts,
                            str(last_error),
                        )
                    raise _ParseError(str(err)) from err
        except _ParseError:
            pass
        except Exception as e:
            last_error = e
            logger.error("%s SDK 调用失败（不重试）: error=%s", log_context, e)

        raise BusinessException(
            error_code,
            f"{error_prefix}{last_error}" if last_error else f"{error_prefix}unknown",
        )

    def _build_retry_prompt(
        self, system_prompt: str, last_error: Exception | None
    ) -> str:
        prompt = system_prompt + "\n\n" + _STRICT_JSON_INSTRUCTION + "\n"
        prompt += "上次输出解析失败，请仅返回合法 JSON。"
        if last_error is not None:
            error_msg = str(last_error)
            if error_msg:
                prompt += f"\n上次失败原因：{self._sanitize_error(error_msg)}"
        return prompt

    def _sanitize_error(self, message: str) -> str:
        one_line = message.replace("\n", " ").replace("\r", " ").strip()
        if len(one_line) > _ERROR_MESSAGE_MAX_LENGTH:
            return one_line[:_ERROR_MESSAGE_MAX_LENGTH] + "..."
        return one_line

    def _try_repair_json(self, raw: object, output_model: type[T]) -> T | None:
        try:
            content = getattr(raw, "content", None)
            if content is None:
                content = str(raw)
            if not isinstance(content, str) or not content.strip():
                return None
            repaired_obj = repair_json(content, return_objects=True)
            if isinstance(repaired_obj, dict):
                return output_model.model_validate(repaired_obj)
        except Exception:
            return None
        return None
