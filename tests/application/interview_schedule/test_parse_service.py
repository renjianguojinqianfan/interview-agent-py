from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.interview_schedule.service import ScheduleParseService
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.structured_output import StructuredOutputInvoker


@pytest.fixture()
def mock_llm_registry() -> MagicMock:
    return MagicMock(spec=LlmProviderRegistry)


@pytest.fixture()
def mock_invoker() -> MagicMock:
    return MagicMock(spec=StructuredOutputInvoker)


@pytest.fixture()
def parse_service(mock_llm_registry: MagicMock, mock_invoker: MagicMock) -> ScheduleParseService:
    return ScheduleParseService(
        llm_registry=mock_llm_registry,
        invoker=mock_invoker,
    )


class TestParseFeishu:
    async def test_parse_feishu_rule_success(self, parse_service: ScheduleParseService) -> None:
        text = (
            "飞书面试邀约\n"
            "公司：阿里巴巴\n"
            "岗位：Java工程师\n"
            "时间：2026-08-01 14:00\n"
            "会议链接：https://meeting.feishu.cn/abc123\n"
            "第二轮面试"
        )

        response = await parse_service.parse(text, "feishu")

        assert response.success is True
        assert response.parse_method == "rule"
        assert response.confidence == 0.95
        assert response.data is not None
        assert response.data.company_name == "阿里巴巴"
        assert response.data.position == "Java工程师"
        assert response.data.interview_type == "VIDEO"
        assert response.data.meeting_link == "https://meeting.feishu.cn/abc123"
        assert response.data.round_number == 2


class TestParseTencent:
    async def test_parse_tencent_rule_success(self, parse_service: ScheduleParseService) -> None:
        text = "腾讯会议邀请\n公司：腾讯科技\n岗位：前端工程师\n2026-08-15 10:00\n会议号：123456789\n密码：1234"

        response = await parse_service.parse(text, "tencent")

        assert response.success is True
        assert response.parse_method == "rule"
        assert response.data is not None
        assert response.data.company_name == "腾讯科技"
        assert response.data.position == "前端工程师"
        assert response.data.interview_type == "VIDEO"
        assert "123456789" in (response.data.meeting_link or "")


class TestParseZoom:
    async def test_parse_zoom_rule_success(self, parse_service: ScheduleParseService) -> None:
        text = "Zoom Meeting Invite\n公司：ZoomInc\n岗位：Engineer\nhttps://zoom.us/j/123456789\n2026-09-01 15:00"

        response = await parse_service.parse(text, "zoom")

        assert response.success is True
        assert response.parse_method == "rule"
        assert response.data is not None
        assert response.data.company_name == "ZoomInc"
        assert response.data.position == "Engineer"
        assert response.data.interview_type == "VIDEO"
        assert "https://zoom.us/j/123456789" in (response.data.meeting_link or "")


class TestParseAutoDetect:
    async def test_auto_detect_feishu(self, parse_service: ScheduleParseService) -> None:
        text = (
            "飞书面试邀约\n"
            "公司：字节跳动\n"
            "岗位：Python工程师\n"
            "时间：2026-08-01 14:00\n"
            "会议链接：https://meeting.feishu.cn/xyz"
        )

        response = await parse_service.parse(text, None)

        assert response.success is True
        assert response.data is not None
        assert response.data.company_name == "字节跳动"


class TestParseEmpty:
    async def test_empty_text_returns_failure(self, parse_service: ScheduleParseService) -> None:
        response = await parse_service.parse("", None)

        assert response.success is False
        assert response.parse_method == "none"
        assert response.data is None


class TestParseLLMFallback:
    async def test_rule_fail_llm_success(
        self, parse_service: ScheduleParseService, mock_llm_registry: MagicMock, mock_invoker: MagicMock
    ) -> None:

        from app.application.interview_schedule.schemas import ParsedScheduleData

        mock_llm = MagicMock()
        mock_llm_registry.get_chat_client = AsyncMock(return_value=mock_llm)

        parsed_data = ParsedScheduleData(
            company_name="美团",
            position="Go工程师",
            interview_time="2026-08-20T14:00:00",
            interview_type="VIDEO",
            round_number=1,
        )
        mock_invoker.invoke = AsyncMock(return_value=parsed_data)

        response = await parse_service.parse("一些不规则的邀约文本无法被规则解析", None)

        assert response.success is True
        assert response.parse_method == "ai"
        assert response.confidence == 0.8
        assert response.data is not None
        assert response.data.company_name == "美团"
        assert response.data.position == "Go工程师"

    async def test_rule_fail_llm_fail_returns_failure(
        self, parse_service: ScheduleParseService, mock_llm_registry: MagicMock, mock_invoker: MagicMock
    ) -> None:
        mock_llm = MagicMock()
        mock_llm_registry.get_chat_client = AsyncMock(return_value=mock_llm)

        mock_invoker.invoke = AsyncMock(side_effect=BusinessException(ErrorCode.AI_SERVICE_ERROR, "LLM error"))

        response = await parse_service.parse("无法解析的文本", None)

        assert response.success is False
        assert response.parse_method == "none"
        assert response.data is None
