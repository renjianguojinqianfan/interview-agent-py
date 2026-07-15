from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from app.api.errors import BusinessException, ErrorCode
from app.infrastructure.ai.prompt_constants import ANTI_INJECTION_INSTRUCTION
from app.infrastructure.ai.structured_output import StructuredOutputInvoker


class SampleOutput(BaseModel):
    name: str
    score: int


def _make_raw_result(
    content: str | None = '{"name": "test", "score": 90}',
    parsed: SampleOutput | None = None,
    parsing_error: Exception | None = None,
) -> dict[str, Any]:
    if parsed is None and parsing_error is None:
        parsed = SampleOutput(name="test", score=90)
    raw = MagicMock()
    raw.content = content
    return {"raw": raw, "parsed": parsed, "parsing_error": parsing_error}


def _make_mock_llm(results: list[dict[str, Any]] | None = None) -> MagicMock:
    mock_llm = MagicMock()
    mock_runnable = MagicMock()
    if results is not None:
        mock_runnable.ainvoke = AsyncMock(side_effect=results)
    else:
        mock_runnable.ainvoke = AsyncMock(return_value=_make_raw_result())
    mock_llm.with_structured_output = MagicMock(return_value=mock_runnable)
    return mock_llm


@pytest.fixture()
def invoker() -> StructuredOutputInvoker:
    return StructuredOutputInvoker(max_attempts=2)


class TestStructuredOutputInvokerSuccess:
    async def test_returns_parsed_result_on_first_attempt(self, invoker: StructuredOutputInvoker) -> None:
        llm = _make_mock_llm()
        result = await invoker.invoke(
            llm=llm,
            system_prompt="You are a tester.",
            user_prompt="Evaluate this.",
            output_model=SampleOutput,
            error_code=ErrorCode.AI_SERVICE_ERROR,
            error_prefix="分析失败: ",
            log_context="test",
        )
        assert result.name == "test"
        assert result.score == 90

    async def test_system_prompt_gets_anti_injection_appended(self, invoker: StructuredOutputInvoker) -> None:
        llm = _make_mock_llm()
        await invoker.invoke(
            llm=llm,
            system_prompt="You are a tester.",
            user_prompt="test",
            output_model=SampleOutput,
            error_code=ErrorCode.AI_SERVICE_ERROR,
            error_prefix="err: ",
            log_context="test",
        )
        call_args = llm.with_structured_output.return_value.ainvoke.call_args
        messages = call_args.args[0]
        system_content = messages[0].content
        assert ANTI_INJECTION_INSTRUCTION in system_content
        assert "You are a tester." in system_content


class TestStructuredOutputInvokerRetry:
    async def test_retries_on_parsing_error_then_succeeds(self, invoker: StructuredOutputInvoker) -> None:
        results = [
            _make_raw_result(parsed=None, parsing_error=Exception("invalid json")),
            _make_raw_result(),
        ]
        llm = _make_mock_llm(results)
        result = await invoker.invoke(
            llm=llm,
            system_prompt="system",
            user_prompt="user",
            output_model=SampleOutput,
            error_code=ErrorCode.AI_SERVICE_ERROR,
            error_prefix="err: ",
            log_context="test",
        )
        assert result.name == "test"

    async def test_raises_after_max_attempts(self, invoker: StructuredOutputInvoker) -> None:
        results = [
            _make_raw_result(
                content="not parseable text",
                parsed=None,
                parsing_error=Exception("bad json 1"),
            ),
            _make_raw_result(
                content="not parseable text",
                parsed=None,
                parsing_error=Exception("bad json 2"),
            ),
        ]
        llm = _make_mock_llm(results)
        with pytest.raises(BusinessException) as exc_info:
            await invoker.invoke(
                llm=llm,
                system_prompt="system",
                user_prompt="user",
                output_model=SampleOutput,
                error_code=ErrorCode.AI_SERVICE_ERROR,
                error_prefix="err: ",
                log_context="test",
            )
        assert exc_info.value.error_code == ErrorCode.AI_SERVICE_ERROR
        assert "err:" in exc_info.value.message

    async def test_retry_prompt_includes_strict_json_instruction(self, invoker: StructuredOutputInvoker) -> None:
        results = [
            _make_raw_result(
                content="not parseable",
                parsed=None,
                parsing_error=Exception("bad json"),
            ),
            _make_raw_result(),
        ]
        llm = _make_mock_llm(results)
        await invoker.invoke(
            llm=llm,
            system_prompt="system",
            user_prompt="user",
            output_model=SampleOutput,
            error_code=ErrorCode.AI_SERVICE_ERROR,
            error_prefix="err: ",
            log_context="test",
        )
        calls = llm.with_structured_output.return_value.ainvoke.call_args_list
        second_call_messages = calls[1].args[0]
        second_system_content = second_call_messages[0].content
        assert "JSON" in second_system_content or "json" in second_system_content
        assert "上次" in second_system_content or "失败" in second_system_content


class TestStructuredOutputInvokerJsonRepair:
    async def test_json_repair_fixes_broken_json(self, invoker: StructuredOutputInvoker) -> None:
        broken_content = '{"name": "test", "score": 90,}'  # trailing comma
        results = [
            _make_raw_result(
                content=broken_content,
                parsed=None,
                parsing_error=Exception("invalid json"),
            ),
        ]
        llm = _make_mock_llm(results)
        result = await invoker.invoke(
            llm=llm,
            system_prompt="system",
            user_prompt="user",
            output_model=SampleOutput,
            error_code=ErrorCode.AI_SERVICE_ERROR,
            error_prefix="err: ",
            log_context="test",
        )
        assert result.name == "test"
        assert result.score == 90


class TestStructuredOutputInvokerSdkError:
    async def test_sdk_error_not_retried_by_tenacity(self, invoker: StructuredOutputInvoker) -> None:
        mock_llm = MagicMock()
        mock_runnable = MagicMock()
        mock_runnable.ainvoke = AsyncMock(side_effect=Exception("network error"))
        mock_llm.with_structured_output = MagicMock(return_value=mock_runnable)

        with pytest.raises(BusinessException) as exc_info:
            await invoker.invoke(
                llm=mock_llm,
                system_prompt="system",
                user_prompt="user",
                output_model=SampleOutput,
                error_code=ErrorCode.AI_SERVICE_ERROR,
                error_prefix="err: ",
                log_context="test",
            )
        assert exc_info.value.error_code == ErrorCode.AI_SERVICE_ERROR
        assert mock_runnable.ainvoke.call_count == 1

    async def test_sdk_error_raises_business_exception_not_swallowed(self, invoker: StructuredOutputInvoker) -> None:
        mock_llm = MagicMock()
        mock_runnable = MagicMock()
        sdk_error = RuntimeError("connection refused")
        mock_runnable.ainvoke = AsyncMock(side_effect=sdk_error)
        mock_llm.with_structured_output = MagicMock(return_value=mock_runnable)

        with pytest.raises(BusinessException) as exc_info:
            await invoker.invoke(
                llm=mock_llm,
                system_prompt="system",
                user_prompt="user",
                output_model=SampleOutput,
                error_code=ErrorCode.AI_SERVICE_TIMEOUT,
                error_prefix="timeout: ",
                log_context="test",
            )
        assert exc_info.value.error_code == ErrorCode.AI_SERVICE_TIMEOUT
        assert "connection refused" in exc_info.value.message


class TestStructuredOutputInvokerMaxAttemptsConfig:
    async def test_single_attempt_config(self) -> None:
        invoker = StructuredOutputInvoker(max_attempts=1)
        results = [
            _make_raw_result(
                content="not parseable",
                parsed=None,
                parsing_error=Exception("bad json"),
            ),
        ]
        llm = _make_mock_llm(results)
        with pytest.raises(BusinessException):
            await invoker.invoke(
                llm=llm,
                system_prompt="system",
                user_prompt="user",
                output_model=SampleOutput,
                error_code=ErrorCode.AI_SERVICE_ERROR,
                error_prefix="err: ",
                log_context="test",
            )
