"""面试日程应用服务：CRUD + 邀约文本解析。

日程 CRUD 是简单模块，不经过 domain 层（per migration-plan.md）。
规则解析算法隔离到 domain/services/schedule_parser.py（纯函数）。
应用层负责 LLM 编排 + ParsedSchedule -> CreateScheduleRequest 转换。
"""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interview_schedule.schemas import (
    CreateScheduleRequest,
    InterviewScheduleDTO,
    ParsedScheduleData,
    ParseResponse,
)
from app.domain.entities.interview_schedule import InterviewStatus, ParsedSchedule
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.schedule_parser import is_valid_parse, parse_by_rules
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.prompt_loader import load_prompt
from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer
from app.infrastructure.ai.structured_output import StructuredOutputInvoker
from app.infrastructure.db.models.interview_schedule import InterviewSchedule
from app.infrastructure.db.repositories.interview_schedule_repository import InterviewScheduleRepository

logger = logging.getLogger(__name__)


class ScheduleService:
    """面试日程 CRUD 服务。"""

    def __init__(
        self,
        session: AsyncSession,
        repository: InterviewScheduleRepository,
    ) -> None:
        self._session = session
        self._repository = repository

    async def create(self, request: CreateScheduleRequest) -> InterviewScheduleDTO:
        schedule = InterviewSchedule(
            company_name=request.company_name,
            position=request.position,
            interview_time=request.interview_time,
            interview_type=request.interview_type,
            meeting_link=request.meeting_link,
            round_number=request.round_number,
            interviewer=request.interviewer,
            notes=request.notes,
            status=InterviewStatus.PENDING.value,
        )
        await self._repository.save(self._session, schedule)
        await self._session.commit()
        logger.info("创建面试日程: %s - %s", request.company_name, request.position)
        return self._to_dto(schedule)

    async def get_by_id(self, schedule_id: int) -> InterviewScheduleDTO:
        schedule = await self._repository.get_by_id(self._session, schedule_id)
        if schedule is None:
            raise BusinessException(ErrorCode.INTERVIEW_SCHEDULE_NOT_FOUND, f"面试日程不存在: {schedule_id}")
        return self._to_dto(schedule)

    async def list_schedules(
        self,
        status: str | None,
        start: datetime | None,
        end: datetime | None,
    ) -> list[InterviewScheduleDTO]:
        if start is not None and end is not None:
            schedules = await self._repository.list_by_time_range(self._session, start, end)
        elif status is not None:
            schedules = await self._repository.list_by_status(self._session, status)
        else:
            schedules = await self._repository.list_all(self._session)
        return [self._to_dto(s) for s in schedules]

    async def update(self, schedule_id: int, request: CreateScheduleRequest) -> InterviewScheduleDTO:
        schedule = await self._repository.get_by_id(self._session, schedule_id)
        if schedule is None:
            raise BusinessException(ErrorCode.INTERVIEW_SCHEDULE_NOT_FOUND, f"面试日程不存在: {schedule_id}")
        schedule.company_name = request.company_name
        schedule.position = request.position
        schedule.interview_time = request.interview_time
        schedule.interview_type = request.interview_type
        schedule.meeting_link = request.meeting_link
        schedule.round_number = request.round_number
        schedule.interviewer = request.interviewer
        schedule.notes = request.notes
        await self._session.commit()
        logger.info("更新面试日程: id=%d", schedule_id)
        return self._to_dto(schedule)

    async def delete(self, schedule_id: int) -> None:
        schedule = await self._repository.get_by_id(self._session, schedule_id)
        if schedule is None:
            raise BusinessException(ErrorCode.INTERVIEW_SCHEDULE_NOT_FOUND, f"面试日程不存在: {schedule_id}")
        await self._repository.delete(self._session, schedule)
        await self._session.commit()
        logger.info("删除面试日程: id=%d", schedule_id)

    async def update_status(self, schedule_id: int, status: InterviewStatus) -> InterviewScheduleDTO:
        schedule = await self._repository.get_by_id(self._session, schedule_id)
        if schedule is None:
            raise BusinessException(ErrorCode.INTERVIEW_SCHEDULE_NOT_FOUND, f"面试日程不存在: {schedule_id}")
        schedule.status = status.value
        await self._session.commit()
        logger.info("更新面试状态: id=%d, status=%s", schedule_id, status.value)
        return self._to_dto(schedule)

    def _to_dto(self, schedule: InterviewSchedule) -> InterviewScheduleDTO:
        return InterviewScheduleDTO(
            id=schedule.id,
            company_name=schedule.company_name,
            position=schedule.position,
            interview_time=schedule.interview_time,
            interview_type=schedule.interview_type,
            meeting_link=schedule.meeting_link,
            round_number=schedule.round_number,
            interviewer=schedule.interviewer,
            notes=schedule.notes,
            status=schedule.status,
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
        )


class ScheduleParseService:
    """面试邀约文本解析服务：规则解析优先 -> LLM 兜底。

    规则解析委托 domain/services/schedule_parser.py（纯函数）。
    规则解析失败时降级到 LLM 结构化输出。
    """

    def __init__(
        self,
        llm_registry: LlmProviderRegistry,
        invoker: StructuredOutputInvoker,
        sanitizer: PromptSanitizer | None = None,
    ) -> None:
        self._llm_registry = llm_registry
        self._invoker = invoker
        self._sanitizer = sanitizer or PromptSanitizer()

    async def parse(self, raw_text: str, source: str | None) -> ParseResponse:
        if not raw_text or not raw_text.strip():
            return ParseResponse(success=False, parse_method="none", log="输入文本为空")

        rule_result = parse_by_rules(raw_text, source)
        if rule_result is not None and is_valid_parse(rule_result):
            logger.info("规则解析成功")
            return ParseResponse(
                success=True,
                data=self._to_request(rule_result),
                confidence=0.95,
                parse_method="rule",
                log="规则解析成功",
            )

        logger.info("规则解析失败，尝试 AI 解析")
        ai_result = await self._parse_with_ai(raw_text)
        if ai_result is not None:
            logger.info("AI 解析成功")
            return ParseResponse(
                success=True,
                data=ai_result,
                confidence=0.8,
                parse_method="ai",
                log="AI 解析成功",
            )

        logger.warning("所有解析方式均失败")
        return ParseResponse(success=False, parse_method="none", log="解析失败")

    async def _parse_with_ai(self, raw_text: str) -> CreateScheduleRequest | None:
        try:
            system_tpl = await load_prompt("interview-schedule-parse-system")
            current_date = datetime.now().strftime("%Y-%m-%d")
            system_prompt = system_tpl.format(current_date=current_date)

            sanitized_text = self._sanitizer.sanitize(raw_text) or ""
            wrapped_text = self._sanitizer.wrap_with_delimiters("邀约文本", sanitized_text)

            llm = await self._llm_registry.get_chat_client()
            parsed = await self._invoker.invoke(
                llm=llm,
                system_prompt=system_prompt,
                user_prompt=wrapped_text,
                output_model=ParsedScheduleData,
                error_code=ErrorCode.AI_SERVICE_ERROR,
                error_prefix="面试邀约解析失败：",
                log_context="面试邀约解析",
            )
            return self._parsed_data_to_request(parsed)
        except BusinessException as e:
            logger.error("AI 解析异常: %s", e)
            return None

    def _to_request(self, parsed: ParsedSchedule) -> CreateScheduleRequest:
        return CreateScheduleRequest(
            company_name=parsed.company_name or "",
            position=parsed.position or "",
            interview_time=parsed.interview_time or datetime(2000, 1, 1),
            interview_type=parsed.interview_type,
            meeting_link=parsed.meeting_link,
            round_number=parsed.round_number,
            interviewer=parsed.interviewer,
            notes=parsed.notes,
        )

    def _parsed_data_to_request(self, parsed: ParsedScheduleData) -> CreateScheduleRequest:
        time_str = parsed.interview_time.strip()
        if len(time_str) == 16:
            time_str += ":00"
        interview_time = datetime.fromisoformat(time_str)

        return CreateScheduleRequest(
            company_name=parsed.company_name,
            position=parsed.position,
            interview_time=interview_time,
            interview_type=parsed.interview_type,
            meeting_link=parsed.meeting_link,
            round_number=parsed.round_number,
            interviewer=parsed.interviewer,
            notes=parsed.notes,
        )
