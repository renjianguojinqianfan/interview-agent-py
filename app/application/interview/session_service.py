"""面试会话应用服务：生命周期编排（创建->出题->答题->交卷->入队评估）。

双写策略：先 DB 后 Redis（Redis 失败仅 warn，读取侧从 DB 恢复）。
事务后发送：COMPLETED + evaluate_status=PENDING 同事务提交，事务后 send_task。
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interview.persistence_service import InterviewPersistenceService
from app.application.interview.question_service import QuestionService
from app.application.interview.schemas import (
    CreateSessionRequest,
    CurrentQuestionResponse,
    InterviewQuestionDTO,
    InterviewSessionDTO,
    SessionListItemDTO,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from app.domain.entities.interview import (
    DEFAULT_DIFFICULTY,
    DEFAULT_SKILL_ID,
    SESSION_ID_LENGTH,
    InterviewQuestion,
    SessionStatus,
)
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.question_codec import deserialize_questions, serialize_questions
from app.domain.services.session_state import is_unfinished, validate_transition
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.redis.session_cache import InterviewSessionCache
from app.infrastructure.tasks.interview_evaluate_producer import EvaluatePayload, EvaluateStreamProducer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SessionView:
    """缓存/DB 恢复后的会话视图（统一结构）。"""

    session_id: str
    resume_id: int | None
    resume_text: str
    current_question_index: int
    status: str
    questions_json: str


class InterviewSessionService:
    """面试会话生命周期编排服务。"""

    def __init__(
        self,
        session: AsyncSession,
        question_service: QuestionService,
        persistence_service: InterviewPersistenceService,
        session_cache: InterviewSessionCache,
        evaluate_producer: EvaluateStreamProducer,
        resume_repository: ResumeRepository,
    ) -> None:
        self._session = session
        self._question_service = question_service
        self._persistence = persistence_service
        self._cache = session_cache
        self._evaluate_producer = evaluate_producer
        self._resume_repository = resume_repository

    async def create_session(self, request: CreateSessionRequest) -> InterviewSessionDTO:
        if request.resume_id and not request.force_create:
            unfinished = await self._find_unfinished_session(request.resume_id)
            if unfinished is not None:
                logger.info("检测到未完成会话，返回现有: resumeId=%s", request.resume_id)
                return unfinished

        resume_text = await self._load_resume_text(request.resume_id) or request.resume_text
        skill_id = request.skill_id or DEFAULT_SKILL_ID
        difficulty = request.difficulty or DEFAULT_DIFFICULTY
        historical = await self._persistence.get_historical_questions(skill_id, request.resume_id)

        questions = await self._question_service.generate(
            skill_id=skill_id,
            difficulty=difficulty,
            resume_text=resume_text,
            question_count=request.question_count,
            historical=historical,
            custom_categories=request.custom_categories or None,
            jd_text=request.jd_text,
            llm_provider=request.llm_provider,
        )

        session_id = uuid.uuid4().hex[:SESSION_ID_LENGTH]
        await self._persistence.save_session(
            session_id=session_id,
            resume_id=request.resume_id,
            total_questions=len(questions),
            questions=questions,
            llm_provider=request.llm_provider,
            skill_id=skill_id,
            difficulty=difficulty,
        )
        await self._session.commit()

        await self._write_cache(session_id, resume_text or "", request.resume_id, questions, 0, SessionStatus.CREATED)

        logger.info("创建面试会话: sessionId=%s, questions=%d", session_id, len(questions))
        return self._build_session_dto(
            session_id, resume_text or "", len(questions), 0, questions, SessionStatus.CREATED
        )

    async def get_session(self, session_id: str) -> InterviewSessionDTO:
        view = await self._get_or_restore_session(session_id)
        return self._view_to_dto(view)

    async def get_current_question(self, session_id: str) -> CurrentQuestionResponse:
        view = await self._get_or_restore_session(session_id)
        questions = deserialize_questions(view.questions_json or "[]")

        if view.current_question_index >= len(questions):
            return CurrentQuestionResponse(completed=True, message="所有问题已回答完毕")

        if view.status == SessionStatus.CREATED.value:
            await self._persistence.update_session_status(session_id, SessionStatus.IN_PROGRESS.value)
            await self._session.commit()
            await self._cache.update_status(session_id, SessionStatus.IN_PROGRESS.value)

        question = questions[view.current_question_index]
        return CurrentQuestionResponse(
            completed=False,
            question=self._question_to_dto(question),
        )

    async def submit_answer(
        self,
        session_id: str,
        request: SubmitAnswerRequest,
    ) -> SubmitAnswerResponse:
        view = await self._get_or_restore_session(session_id)
        if not is_unfinished(SessionStatus(view.status)):
            raise BusinessException(ErrorCode.INTERVIEW_ALREADY_COMPLETED)
        questions = deserialize_questions(view.questions_json or "[]")

        index = request.question_index
        if index < 0 or index >= len(questions):
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND, f"无效的问题索引: {index}")

        question = questions[index]
        questions[index] = question.with_answer(request.answer)
        new_index = index + 1
        has_next = new_index < len(questions)
        next_question = questions[new_index] if has_next else None

        await self._persistence.save_answer(session_id, index, question.question, question.category, request.answer)

        if has_next:
            await self._persistence.update_current_question_index(session_id, new_index)
            await self._session.commit()
            await self._cache.update_questions(session_id, serialize_questions(questions))
            await self._cache.update_current_index(session_id, new_index)
        else:
            await self._persistence.update_session_status(session_id, SessionStatus.COMPLETED.value)
            await self._persistence.update_evaluate_status(session_id, "PENDING", None)
            await self._session.commit()
            await self._cache.update_questions(session_id, serialize_questions(questions))
            await self._cache.update_status(session_id, SessionStatus.COMPLETED.value)
            await self._enqueue_evaluation(session_id)
            if view.resume_id is not None:
                await self._cache.delete_unfinished_mapping(view.resume_id)

        logger.info("提交答案: sessionId=%s, index=%d, hasNext=%s", session_id, index, has_next)
        return SubmitAnswerResponse(
            has_next_question=has_next,
            next_question=self._question_to_dto(next_question) if next_question else None,
            current_index=new_index,
            total_questions=len(questions),
        )

    async def save_answer(self, session_id: str, request: SubmitAnswerRequest) -> None:
        view = await self._get_or_restore_session(session_id)
        if not is_unfinished(SessionStatus(view.status)):
            raise BusinessException(ErrorCode.INTERVIEW_ALREADY_COMPLETED)
        questions = deserialize_questions(view.questions_json or "[]")

        index = request.question_index
        if index < 0 or index >= len(questions):
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND, f"无效的问题索引: {index}")

        question = questions[index]
        await self._persistence.save_answer(session_id, index, question.question, question.category, request.answer)
        if view.status == SessionStatus.CREATED.value:
            await self._persistence.update_session_status(session_id, SessionStatus.IN_PROGRESS.value)
        await self._session.commit()

        questions[index] = question.with_answer(request.answer)
        await self._cache.update_questions(session_id, serialize_questions(questions))
        logger.info("暂存答案: sessionId=%s, index=%d", session_id, index)

    async def complete_interview(self, session_id: str) -> None:
        view = await self._get_or_restore_session(session_id)
        current = SessionStatus(view.status)
        validate_transition(current, SessionStatus.COMPLETED)

        await self._persistence.update_session_status(session_id, SessionStatus.COMPLETED.value)
        await self._persistence.update_evaluate_status(session_id, "PENDING", None)
        await self._session.commit()

        await self._cache.update_status(session_id, SessionStatus.COMPLETED.value)
        await self._enqueue_evaluation(session_id)
        if view.resume_id is not None:
            await self._cache.delete_unfinished_mapping(view.resume_id)
        logger.info("提前交卷: sessionId=%s", session_id)

    async def find_unfinished_session(self, resume_id: int) -> InterviewSessionDTO:
        dto = await self._find_unfinished_session(resume_id)
        if dto is None:
            raise BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND, "未找到未完成的面试会话")
        return dto

    async def list_sessions(self) -> list[SessionListItemDTO]:
        sessions = await self._persistence.find_all()
        return [self._orm_to_list_item(s) for s in sessions]

    async def delete_session(self, session_id: str) -> None:
        orm = await self._persistence.find_by_session_id_optional(session_id)
        if orm is not None:
            resume_id = orm.resume_id
            await self._persistence.delete_session(session_id)
            await self._session.commit()
            await self._cache.delete_session(session_id)
            if resume_id is not None:
                unfinished_id = await self._cache.find_unfinished_session_id(resume_id)
                if unfinished_id == session_id:
                    await self._cache.delete_unfinished_mapping(resume_id)
        logger.info("删除面试会话: sessionId=%s", session_id)

    async def _find_unfinished_session(self, resume_id: int) -> InterviewSessionDTO | None:
        cached_id = await self._cache.find_unfinished_session_id(resume_id)
        if cached_id is not None:
            cached = await self._cache.get_session(cached_id)
            if cached is not None:
                if not is_unfinished(SessionStatus(cached.status)):
                    await self._cache.delete_unfinished_mapping(resume_id)
                else:
                    questions = deserialize_questions(cached.questions_json)
                    return self._build_session_dto(
                        cached.session_id,
                        cached.resume_text,
                        len(questions),
                        cached.current_index,
                        questions,
                        SessionStatus(cached.status),
                    )

        orm = await self._persistence.find_unfinished_by_resume_id(resume_id)
        if orm is None:
            return None
        return await self._restore_from_orm(orm)

    async def _get_or_restore_session(self, session_id: str) -> _SessionView:
        cached = await self._cache.get_session(session_id)
        if cached is not None:
            await self._cache.refresh_ttl(session_id)
            return _SessionView(
                session_id=cached.session_id,
                resume_id=cached.resume_id,
                resume_text=cached.resume_text,
                current_question_index=cached.current_index,
                status=cached.status,
                questions_json=cached.questions_json,
            )

        orm = await self._persistence.find_by_session_id_optional(session_id)
        if orm is None:
            raise BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND)

        answers = await self._persistence.find_answers_by_session_id(session_id)
        questions = deserialize_questions(orm.questions_json or "[]")
        for ans in answers:
            if 0 <= ans.question_index < len(questions):
                questions[ans.question_index] = questions[ans.question_index].with_answer(ans.user_answer or "")
        questions_json = serialize_questions(questions)
        resume_text = await self._load_resume_text(orm.resume_id) or ""
        await self._write_cache_str(
            session_id, resume_text, orm.resume_id, questions_json, orm.current_question_index, orm.status
        )
        return _SessionView(
            session_id=session_id,
            resume_id=orm.resume_id,
            resume_text="",
            current_question_index=orm.current_question_index,
            status=orm.status,
            questions_json=questions_json,
        )

    async def _restore_from_orm(self, orm: InterviewSessionORM) -> InterviewSessionDTO:
        answers = await self._persistence.find_answers_by_session_id(orm.session_id)
        questions = deserialize_questions(orm.questions_json or "[]")
        for ans in answers:
            if 0 <= ans.question_index < len(questions):
                questions[ans.question_index] = questions[ans.question_index].with_answer(ans.user_answer or "")
        resume_text = await self._load_resume_text(orm.resume_id) or ""
        await self._write_cache(
            orm.session_id, resume_text, orm.resume_id, questions, orm.current_question_index, SessionStatus(orm.status)
        )
        return self._build_session_dto(
            orm.session_id,
            resume_text,
            len(questions),
            orm.current_question_index,
            questions,
            SessionStatus(orm.status),
        )

    async def _load_resume_text(self, resume_id: int | None) -> str | None:
        if resume_id is None:
            return None
        resume = await self._resume_repository.get_by_id(self._session, resume_id)
        return resume.resume_text if resume else None

    async def _enqueue_evaluation(self, session_id: str) -> None:
        await self._evaluate_producer.send_task(EvaluatePayload(session_id=session_id))

    async def _write_cache(
        self,
        session_id: str,
        resume_text: str,
        resume_id: int | None,
        questions: list[InterviewQuestion],
        current_index: int,
        status: SessionStatus,
    ) -> None:
        questions_json = serialize_questions(questions)
        await self._write_cache_str(session_id, resume_text, resume_id, questions_json, current_index, status.value)

    async def _write_cache_str(
        self,
        session_id: str,
        resume_text: str,
        resume_id: int | None,
        questions_json: str,
        current_index: int,
        status: str,
    ) -> None:
        try:
            await self._cache.save_session(
                session_id=session_id,
                resume_text=resume_text,
                resume_id=resume_id,
                questions_json=questions_json,
                current_index=current_index,
                status=status,
            )
        except Exception as e:
            logger.warning("Redis 缓存写入失败，不影响主流程: sessionId=%s, error=%s", session_id, e)

    def _view_to_dto(self, view: _SessionView) -> InterviewSessionDTO:
        questions = deserialize_questions(view.questions_json or "[]")
        return self._build_session_dto(
            view.session_id,
            view.resume_text,
            len(questions),
            view.current_question_index,
            questions,
            SessionStatus(view.status),
        )

    def _build_session_dto(
        self,
        session_id: str,
        resume_text: str,
        total: int,
        current_index: int,
        questions: list[InterviewQuestion],
        status: SessionStatus,
    ) -> InterviewSessionDTO:
        return InterviewSessionDTO(
            session_id=session_id,
            resume_text=resume_text,
            total_questions=total,
            current_question_index=current_index,
            questions=[self._question_to_dto(q) for q in questions],
            status=status.value,
        )

    def _question_to_dto(self, q: InterviewQuestion) -> InterviewQuestionDTO:
        return InterviewQuestionDTO(
            question_index=q.question_index,
            question=q.question,
            type=q.type,
            category=q.category,
            topic_summary=q.topic_summary,
            user_answer=q.user_answer,
            score=q.score,
            feedback=q.feedback,
            is_follow_up=q.is_follow_up,
            parent_question_index=q.parent_question_index,
        )

    def _orm_to_list_item(self, orm: InterviewSessionORM) -> SessionListItemDTO:
        return SessionListItemDTO(
            session_id=orm.session_id,
            skill_id=orm.skill_id,
            difficulty=orm.difficulty,
            resume_id=orm.resume_id,
            total_questions=orm.total_questions,
            status=orm.status,
            evaluate_status=orm.evaluate_status,
            evaluate_error=orm.evaluate_error,
            overall_score=orm.overall_score,
            created_at=orm.created_at,
            completed_at=orm.completed_at,
        )
