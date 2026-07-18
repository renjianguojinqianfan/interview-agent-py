"""面试持久化服务：封装 InterviewRepository，处理 questions JSON 序列化与 domain<->ORM 转换。"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.interview import (
    HistoricalQuestion,
    InterviewQuestion,
    SessionStatus,
)
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.question_gen import dedupe_historical
from app.infrastructure.db.models.interview import InterviewAnswer as InterviewAnswerORM
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM
from app.infrastructure.db.repositories.interview_repository import InterviewRepository

logger = logging.getLogger(__name__)


class InterviewPersistenceService:
    """DB 持久化封装。每个方法接收 AsyncSession，不在内部管理事务（由调用方 commit）。"""

    def __init__(self, session: AsyncSession, repository: InterviewRepository) -> None:
        self._session = session
        self._repository = repository

    async def save_session(
        self,
        session_id: str,
        resume_id: int | None,
        total_questions: int,
        questions: list[InterviewQuestion],
        llm_provider: str | None,
        skill_id: str,
        difficulty: str,
    ) -> InterviewSessionORM:
        orm = InterviewSessionORM(
            session_id=session_id,
            skill_id=skill_id,
            difficulty=difficulty,
            resume_id=resume_id,
            total_questions=total_questions,
            current_question_index=0,
            status=SessionStatus.CREATED.value,
            questions_json=self.serialize_questions(questions),
            llm_provider=llm_provider,
        )
        return await self._repository.save_session(self._session, orm)

    async def find_by_session_id(self, session_id: str) -> InterviewSessionORM:
        orm = await self._repository.find_by_session_id(self._session, session_id)
        if orm is None:
            raise BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND)
        return orm

    async def find_by_session_id_optional(self, session_id: str) -> InterviewSessionORM | None:
        return await self._repository.find_by_session_id(self._session, session_id)

    async def update_session_status(self, session_id: str, status: str) -> None:
        orm = await self.find_by_session_id(session_id)
        await self._repository.update_session_status(self._session, orm, status)

    async def update_current_question_index(self, session_id: str, index: int) -> None:
        orm = await self.find_by_session_id(session_id)
        await self._repository.update_current_question_index(self._session, orm, index)

    async def update_evaluate_status(
        self,
        session_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        orm = await self.find_by_session_id(session_id)
        await self._repository.update_evaluate_status(self._session, orm, status, error)

    async def save_answer(
        self,
        session_id: str,
        question_index: int,
        question: str,
        category: str,
        user_answer: str,
    ) -> InterviewAnswerORM:
        orm = await self.find_by_session_id(session_id)
        existing = await self._repository.find_answer_by_session_and_index(self._session, orm.id, question_index)
        if existing is not None:
            existing.question = question
            existing.category = category
            existing.user_answer = user_answer
            return existing
        answer = InterviewAnswerORM(
            session_id=orm.id,
            question_index=question_index,
            question=question,
            category=category,
            user_answer=user_answer,
        )
        return await self._repository.save_answer(self._session, answer)

    async def find_unfinished_by_resume_id(
        self,
        resume_id: int,
    ) -> InterviewSessionORM | None:
        return await self._repository.find_unfinished_by_resume_id(self._session, resume_id)

    async def find_all_paginated(
        self,
        page: int,
        size: int,
        status: str | None = None,
    ) -> tuple[list[InterviewSessionORM], int]:
        return await self._repository.find_all_paginated(self._session, page, size, status)

    async def find_answers_by_session_id(self, session_id: str) -> list[InterviewAnswerORM]:
        orm = await self.find_by_session_id(session_id)
        return await self._repository.find_answers_by_session_id(self._session, orm.id)

    async def get_historical_questions(
        self,
        skill_id: str,
        resume_id: int | None,
    ) -> list[HistoricalQuestion]:
        sessions = await self._repository.find_recent_sessions_for_history(self._session, skill_id, resume_id)
        raw: list[HistoricalQuestion] = []
        for s in sessions:
            if not s.questions_json:
                continue
            try:
                items = json.loads(s.questions_json)
            except json.JSONDecodeError:
                logger.warning("历史会话 questionsJson 解析失败: sessionId=%s", s.session_id)
                continue
            for item in items:
                if item.get("isFollowUp"):
                    continue
                raw.append(
                    HistoricalQuestion(
                        question=item.get("question", ""),
                        type=item.get("type"),
                        topic_summary=item.get("topicSummary"),
                    )
                )

        return dedupe_historical(raw)

    async def delete_session(self, session_id: str) -> None:
        orm = await self.find_by_session_id(session_id)
        await self._repository.delete(self._session, orm)

    @staticmethod
    def serialize_questions(questions: list[InterviewQuestion]) -> str:
        return json.dumps(
            [
                {
                    "questionIndex": q.question_index,
                    "question": q.question,
                    "type": q.type,
                    "category": q.category,
                    "topicSummary": q.topic_summary,
                    "userAnswer": q.user_answer,
                    "score": q.score,
                    "feedback": q.feedback,
                    "isFollowUp": q.is_follow_up,
                    "parentQuestionIndex": q.parent_question_index,
                }
                for q in questions
            ],
            ensure_ascii=False,
        )

    @staticmethod
    def deserialize_questions(questions_json: str) -> list[InterviewQuestion]:
        items = json.loads(questions_json)
        return [
            InterviewQuestion(
                question_index=item["questionIndex"],
                question=item["question"],
                type=item["type"],
                category=item["category"],
                topic_summary=item.get("topicSummary"),
                user_answer=item.get("userAnswer"),
                score=item.get("score"),
                feedback=item.get("feedback"),
                is_follow_up=item.get("isFollowUp", False),
                parent_question_index=item.get("parentQuestionIndex"),
            )
            for item in items
        ]
