"""语音面试应用服务：会话生命周期 + 评估读侧。

事务边界由本服务持有（每个写方法自行 commit）；事务后发送遵循 ADR-0008 显式顺序
（先 commit 再 send，on_send_failed 降级标记 FAILED）。Redis 缓存失败仅 warn。
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interview.schemas import (
    CategoryScoreDTO,
    QuestionEvaluationDetailDTO,
    ReferenceAnswerDTO,
)
from app.application.voice.schemas import (
    CreateVoiceSessionRequest,
    VoiceEvaluationDetailDTO,
    VoiceEvaluationStatusDTO,
    VoiceMessageDTO,
    VoiceSessionDTO,
    VoiceSessionMetaDTO,
)
from app.domain.entities.evaluation import CategoryScore, QuestionEvaluation
from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.entities.voice_interview import (
    DEFAULT_USER_ID,
    InterviewPhase,
    VoiceSessionStatus,
)
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.evaluation import compute_category_scores
from app.domain.services.voice_session_state import validate_transition
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewEvaluation as VoiceInterviewEvaluationORM,
)
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewMessage as VoiceInterviewMessageORM,
)
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewSession as VoiceInterviewSessionORM,
)
from app.infrastructure.db.repositories.voice_interview_repository import VoiceInterviewRepository
from app.infrastructure.json_utils import json_loads_dict_list, json_loads_list
from app.infrastructure.redis.voice_session_cache import (
    CachedVoiceSession,
    VoiceInterviewSessionCache,
)
from app.infrastructure.tasks.voice_evaluate_producer import (
    VoiceEvaluatePayload,
    VoiceEvaluateStreamProducer,
)

logger = logging.getLogger(__name__)

_PHASE_ORDER = (
    (InterviewPhase.INTRO, "intro_enabled"),
    (InterviewPhase.TECH, "tech_enabled"),
    (InterviewPhase.PROJECT, "project_enabled"),
    (InterviewPhase.HR, "hr_enabled"),
)


class VoiceSessionService:
    """语音面试会话生命周期应用服务。"""

    def __init__(
        self,
        session: AsyncSession,
        repository: VoiceInterviewRepository,
        session_cache: VoiceInterviewSessionCache,
        evaluate_producer: VoiceEvaluateStreamProducer,
    ) -> None:
        self._session = session
        self._repository = repository
        self._cache = session_cache
        self._producer = evaluate_producer

    async def create_session(self, request: CreateVoiceSessionRequest) -> VoiceSessionDTO:
        orm = VoiceInterviewSessionORM(
            user_id=DEFAULT_USER_ID,
            role_type=request.role_type,
            skill_id=request.skill_id,
            difficulty=request.difficulty,
            custom_jd_text=request.custom_jd_text,
            resume_id=request.resume_id,
            intro_enabled=request.intro_enabled,
            tech_enabled=request.tech_enabled,
            project_enabled=request.project_enabled,
            hr_enabled=request.hr_enabled,
            llm_provider=str(request.llm_provider_id) if request.llm_provider_id is not None else None,
            current_phase=_determine_first_phase(request),
            status=VoiceSessionStatus.IN_PROGRESS.value,
            planned_duration=request.planned_duration,
        )
        await self._repository.save_session(self._session, orm)
        await self._session.commit()
        await self._write_cache(orm)
        return _to_session_dto(orm)

    async def get_session(self, session_id: int) -> VoiceSessionDTO:
        orm = await self._load_session(session_id)
        return _to_session_dto(orm)

    async def end_session(self, session_id: int) -> None:
        orm = await self._load_session(session_id)
        validate_transition(VoiceSessionStatus(orm.status), VoiceSessionStatus.COMPLETED)
        now = datetime.now(UTC)
        orm.end_time = now
        orm.current_phase = InterviewPhase.COMPLETED.value
        orm.status = VoiceSessionStatus.COMPLETED.value
        orm.actual_duration = int((now - orm.start_time).total_seconds())
        orm.evaluate_status = AsyncTaskStatus.PENDING.value
        orm.evaluate_error = None
        await self._session.commit()
        await self._invalidate_cache(session_id)
        await self._producer.send_task(VoiceEvaluatePayload(session_id=orm.id))

    async def pause_session(self, session_id: int, reason: str = "user_initiated") -> None:
        orm = await self._load_session(session_id)
        validate_transition(VoiceSessionStatus(orm.status), VoiceSessionStatus.PAUSED)
        orm.status = VoiceSessionStatus.PAUSED.value
        orm.paused_at = datetime.now(UTC)
        await self._session.commit()
        await self._invalidate_cache(session_id)
        logger.info("语音会话已暂停: sessionId=%s, reason=%s", session_id, reason)

    async def resume_session(self, session_id: int) -> VoiceSessionDTO:
        orm = await self._load_session(session_id)
        validate_transition(VoiceSessionStatus(orm.status), VoiceSessionStatus.IN_PROGRESS)
        orm.status = VoiceSessionStatus.IN_PROGRESS.value
        orm.resumed_at = datetime.now(UTC)
        await self._session.commit()
        await self._write_cache(orm)
        return _to_session_dto(orm)

    async def list_sessions(
        self,
        user_id: str | None = None,
        status: str | None = None,
    ) -> list[VoiceSessionMetaDTO]:
        target_user = user_id if user_id is not None else DEFAULT_USER_ID
        rows = await self._repository.list_by_user(self._session, target_user, status)
        return [_to_meta_dto(r) for r in rows]

    async def delete_session(self, session_id: int) -> None:
        orm = await self._load_session(session_id)
        await self._repository.delete(self._session, orm)
        await self._session.commit()
        await self._invalidate_cache(session_id)

    async def get_messages(self, session_id: int) -> list[VoiceMessageDTO]:
        orm = await self._load_session(session_id)
        messages = await self._repository.find_messages_by_session(self._session, orm.id)
        return [_to_message_dto(m) for m in messages]

    async def trigger_evaluation(self, session_id: int) -> VoiceEvaluationStatusDTO:
        orm = await self._load_session(session_id)
        current = orm.evaluate_status
        if current in (
            AsyncTaskStatus.COMPLETED.value,
            AsyncTaskStatus.PENDING.value,
            AsyncTaskStatus.PROCESSING.value,
        ):
            return VoiceEvaluationStatusDTO(evaluate_status=current or "")
        orm.evaluate_status = AsyncTaskStatus.PENDING.value
        orm.evaluate_error = None
        await self._session.commit()
        await self._producer.send_task(VoiceEvaluatePayload(session_id=orm.id))
        return VoiceEvaluationStatusDTO(evaluate_status=AsyncTaskStatus.PENDING.value)

    async def _load_session(self, session_id: int) -> VoiceInterviewSessionORM:
        orm = await self._repository.get_by_id(self._session, session_id)
        if orm is None:
            raise BusinessException(ErrorCode.VOICE_SESSION_NOT_FOUND, f"会话不存在: {session_id}")
        return orm

    async def _write_cache(self, orm: VoiceInterviewSessionORM) -> None:
        try:
            await self._cache.save_session(_to_cache_snapshot(orm))
        except Exception as e:
            logger.warning("语音会话缓存写入失败: sessionId=%s, error=%s", orm.id, e)

    async def _invalidate_cache(self, session_id: int) -> None:
        try:
            await self._cache.delete_session(session_id)
        except Exception as e:
            logger.warning("语音会话缓存失效失败: sessionId=%s, error=%s", session_id, e)


class VoiceEvaluationService:
    """语音面试评估读侧服务：查询评估状态与结果。"""

    def __init__(
        self,
        session: AsyncSession,
        repository: VoiceInterviewRepository,
    ) -> None:
        self._session = session
        self._repository = repository

    async def get_evaluation(self, session_id: int) -> VoiceEvaluationStatusDTO:
        orm = await self._repository.get_by_id(self._session, session_id)
        if orm is None:
            raise BusinessException(ErrorCode.VOICE_SESSION_NOT_FOUND, f"会话不存在: {session_id}")
        evaluate_status = orm.evaluate_status or ""
        detail: VoiceEvaluationDetailDTO | None = None
        if evaluate_status == AsyncTaskStatus.COMPLETED.value:
            evaluation = await self._repository.get_evaluation_by_session(self._session, orm.id)
            if evaluation is not None:
                detail = _to_evaluation_detail(evaluation)
        return VoiceEvaluationStatusDTO(evaluate_status=evaluate_status, evaluation=detail)


def _determine_first_phase(request: CreateVoiceSessionRequest) -> str:
    for phase, flag in _PHASE_ORDER:
        if getattr(request, flag):
            return phase.value
    return InterviewPhase.INTRO.value


def _to_session_dto(orm: VoiceInterviewSessionORM) -> VoiceSessionDTO:
    return VoiceSessionDTO(
        id=orm.id,
        session_id=orm.id,
        user_id=orm.user_id,
        role_type=orm.role_type,
        skill_id=orm.skill_id,
        difficulty=orm.difficulty,
        custom_jd_text=orm.custom_jd_text,
        resume_id=orm.resume_id,
        intro_enabled=orm.intro_enabled,
        tech_enabled=orm.tech_enabled,
        project_enabled=orm.project_enabled,
        hr_enabled=orm.hr_enabled,
        llm_provider=orm.llm_provider,
        current_phase=orm.current_phase,
        status=orm.status,
        planned_duration=orm.planned_duration,
        actual_duration=orm.actual_duration,
        start_time=orm.start_time,
        end_time=orm.end_time,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
        paused_at=orm.paused_at,
        resumed_at=orm.resumed_at,
        evaluate_status=orm.evaluate_status,
    )


def _to_meta_dto(orm: VoiceInterviewSessionORM) -> VoiceSessionMetaDTO:
    return VoiceSessionMetaDTO(
        id=orm.id,
        session_id=orm.id,
        role_type=orm.role_type,
        skill_id=orm.skill_id,
        status=orm.status,
        current_phase=orm.current_phase,
        start_time=orm.start_time,
        end_time=orm.end_time,
        evaluate_status=orm.evaluate_status,
        updated_at=orm.updated_at,
    )


def _to_message_dto(orm: VoiceInterviewMessageORM) -> VoiceMessageDTO:
    return VoiceMessageDTO(
        id=orm.id,
        session_id=orm.session_id,
        message_type=orm.message_type,
        phase=orm.phase,
        user_recognized_text=orm.user_recognized_text,
        ai_generated_text=orm.ai_generated_text,
        timestamp=orm.timestamp,
        sequence_num=orm.sequence_num,
    )


def _to_cache_snapshot(orm: VoiceInterviewSessionORM) -> CachedVoiceSession:
    return CachedVoiceSession(
        session_id=str(orm.id),
        user_id=orm.user_id,
        role_type=orm.role_type,
        skill_id=orm.skill_id,
        difficulty=orm.difficulty,
        current_phase=orm.current_phase,
        status=orm.status,
        resume_id=orm.resume_id,
        llm_provider=orm.llm_provider,
    )


def _to_evaluation_detail(orm: VoiceInterviewEvaluationORM) -> VoiceEvaluationDetailDTO:
    question_details = _parse_question_details(orm.question_evaluations_json)
    domain_scores = compute_category_scores(_to_domain_evaluations(question_details))
    category_scores = _to_category_dtos(domain_scores)
    return VoiceEvaluationDetailDTO(
        overall_score=orm.overall_score or 0,
        overall_feedback=orm.overall_feedback or "",
        category_scores=category_scores,
        question_details=question_details,
        strengths=[str(s) for s in json_loads_list(orm.strengths_json)],
        improvements=[str(s) for s in json_loads_list(orm.improvements_json)],
        reference_answers=_parse_reference_answers(orm.reference_answers_json),
    )


def _parse_question_details(raw: str | None) -> list[QuestionEvaluationDetailDTO]:
    items = json_loads_dict_list(raw)
    result: list[QuestionEvaluationDetailDTO] = []
    for item in items:
        result.append(
            QuestionEvaluationDetailDTO(
                question_index=int(item.get("questionIndex", 0)),
                question=str(item.get("question", "")),
                category=str(item.get("category", "")),
                user_answer=item.get("userAnswer"),
                score=int(item.get("score", 0)),
                feedback=str(item.get("feedback", "")),
            )
        )
    return result


def _parse_reference_answers(raw: str | None) -> list[ReferenceAnswerDTO]:
    items = json_loads_dict_list(raw)
    result: list[ReferenceAnswerDTO] = []
    for item in items:
        result.append(
            ReferenceAnswerDTO(
                question_index=int(item.get("questionIndex", 0)),
                question=str(item.get("question", "")),
                reference_answer=str(item.get("referenceAnswer", "")),
                key_points=list(item.get("keyPoints", [])),
            )
        )
    return result


def _to_domain_evaluations(
    details: list[QuestionEvaluationDetailDTO],
) -> list[QuestionEvaluation]:
    """DTO -> domain 评估实体（字段一致），供统一评估领域服务消费。"""
    return [
        QuestionEvaluation(
            question_index=d.question_index,
            question=d.question,
            category=d.category,
            user_answer=d.user_answer,
            score=d.score,
            feedback=d.feedback,
        )
        for d in details
    ]


def _to_category_dtos(scores: list[CategoryScore]) -> list[CategoryScoreDTO]:
    """domain CategoryScore -> DTO。"""
    return [CategoryScoreDTO(category=s.category, score=s.score, question_count=s.question_count) for s in scores]
