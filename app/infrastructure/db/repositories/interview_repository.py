from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.interview import SessionStatus
from app.infrastructure.db.models.interview import InterviewAnswer as InterviewAnswerORM
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM

_UNFINISHED_STATUSES = (SessionStatus.CREATED.value, SessionStatus.IN_PROGRESS.value)
_COMPLETED_STATUSES = (SessionStatus.COMPLETED.value, SessionStatus.EVALUATED.value)
_HISTORICAL_SESSION_LIMIT = 10


class InterviewRepository:
    """面试会话与答案的异步仓储。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def save_session(
        self,
        session: AsyncSession,
        interview_session: InterviewSessionORM,
    ) -> InterviewSessionORM:
        session.add(interview_session)
        await session.flush()
        return interview_session

    async def find_by_session_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> InterviewSessionORM | None:
        result = await session.execute(select(InterviewSessionORM).where(InterviewSessionORM.session_id == session_id))
        return result.scalar_one_or_none()

    async def update_session_status(
        self,
        session: AsyncSession,
        interview_session: InterviewSessionORM,
        status: str,
    ) -> None:
        interview_session.status = status
        if status in _COMPLETED_STATUSES:
            interview_session.completed_at = datetime.now()
        await session.flush()

    async def update_current_question_index(
        self,
        session: AsyncSession,
        interview_session: InterviewSessionORM,
        index: int,
    ) -> None:
        interview_session.current_question_index = index
        await session.flush()

    async def update_evaluate_status(
        self,
        session: AsyncSession,
        interview_session: InterviewSessionORM,
        status: str,
        error: str | None = None,
    ) -> None:
        interview_session.evaluate_status = status
        interview_session.evaluate_error = error
        await session.flush()

    async def save_evaluation_result(
        self,
        session: AsyncSession,
        interview_session: InterviewSessionORM,
        overall_score: int,
        overall_feedback: str,
        strengths_json: str,
        improvements_json: str,
        reference_answers_json: str,
    ) -> None:
        """写入评估结果并将会话置 EVALUATED（评估消费侧专用，#9）。"""
        interview_session.overall_score = overall_score
        interview_session.overall_feedback = overall_feedback
        interview_session.strengths_json = strengths_json
        interview_session.improvements_json = improvements_json
        interview_session.reference_answers_json = reference_answers_json
        interview_session.status = SessionStatus.EVALUATED.value
        interview_session.completed_at = datetime.now()
        await session.flush()

    async def update_answer_evaluation(
        self,
        session: AsyncSession,
        answer: InterviewAnswerORM,
        score: int,
        feedback: str,
        reference_answer: str,
        key_points_json: str,
    ) -> None:
        """回写单题评估结果（score/feedback/reference_answer/key_points）。"""
        answer.score = score
        answer.feedback = feedback
        answer.reference_answer = reference_answer
        answer.key_points_json = key_points_json
        await session.flush()

    async def find_unfinished_by_resume_id(
        self,
        session: AsyncSession,
        resume_id: int,
    ) -> InterviewSessionORM | None:
        result = await session.execute(
            select(InterviewSessionORM)
            .where(InterviewSessionORM.resume_id == resume_id)
            .where(InterviewSessionORM.status.in_(_UNFINISHED_STATUSES))
            .order_by(InterviewSessionORM.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def find_all_paginated(
        self,
        session: AsyncSession,
        page: int,
        size: int,
    ) -> tuple[list[InterviewSessionORM], int]:
        offset = (page - 1) * size
        items_result = await session.execute(
            select(InterviewSessionORM).order_by(InterviewSessionORM.created_at.desc()).offset(offset).limit(size)
        )
        items = list(items_result.scalars().all())
        count_result = await session.execute(select(func.count()).select_from(InterviewSessionORM))
        total = int(count_result.scalar() or 0)
        return items, total

    async def delete(
        self,
        session: AsyncSession,
        interview_session: InterviewSessionORM,
    ) -> None:
        await session.delete(interview_session)

    async def save_answer(
        self,
        session: AsyncSession,
        answer: InterviewAnswerORM,
    ) -> InterviewAnswerORM:
        session.add(answer)
        await session.flush()
        return answer

    async def find_answer_by_session_and_index(
        self,
        session: AsyncSession,
        session_pk: int,
        question_index: int,
    ) -> InterviewAnswerORM | None:
        result = await session.execute(
            select(InterviewAnswerORM)
            .where(InterviewAnswerORM.session_id == session_pk)
            .where(InterviewAnswerORM.question_index == question_index)
        )
        return result.scalar_one_or_none()

    async def find_answers_by_session_id(
        self,
        session: AsyncSession,
        session_pk: int,
    ) -> list[InterviewAnswerORM]:
        result = await session.execute(
            select(InterviewAnswerORM)
            .where(InterviewAnswerORM.session_id == session_pk)
            .order_by(InterviewAnswerORM.question_index)
        )
        return list(result.scalars().all())

    async def find_recent_sessions_for_history(
        self,
        session: AsyncSession,
        skill_id: str,
        resume_id: int | None,
    ) -> list[InterviewSessionORM]:
        """查询最近 10 个同 skillId（有 resumeId 时精确匹配）会话，用于历史题去重。"""
        query = select(InterviewSessionORM).where(InterviewSessionORM.skill_id == skill_id)
        if resume_id is not None:
            query = query.where(InterviewSessionORM.resume_id == resume_id)
        query = query.order_by(InterviewSessionORM.created_at.desc()).limit(_HISTORICAL_SESSION_LIMIT)
        result = await session.execute(query)
        return list(result.scalars().all())
