"""面试评估 Stream 消费者：消费 interview:evaluate:stream，调用统一评估子图并持久化。

幂等策略：should_skip 恒 False（同步方法无法做异步 DB 检查）；幂等下沉到
mark_processing（COMPLETED 不转 PROCESSING）与 process_business（COMPLETED/已删除跳过）。

QaRecord 双源合并：questions_json 提供完整题列表（question/category，userAnswer 恒 None），
interview_answers 表提供权威 user_answer（DB questions_json 不回写 user_answer）。
"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.interview.persistence_service import InterviewPersistenceService
from app.domain.entities.evaluation import EvaluationReport, QaRecord
from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.services.evaluation import build_qa_records, overlay_answers
from app.graphs.evaluation import EvaluationGraph
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.db.models.interview import InterviewAnswer as InterviewAnswerORM
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM
from app.infrastructure.db.repositories.interview_repository import InterviewRepository
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_consumer import BaseStreamConsumer
from app.infrastructure.tasks.constants import FIELD_RETRY_COUNT, STREAM_MAX_LEN, StreamConfig
from app.infrastructure.tasks.interview_evaluate_producer import EvaluatePayload

logger = logging.getLogger(__name__)


class EvaluateStreamConsumer(BaseStreamConsumer[EvaluatePayload]):
    """面试评估 Stream 消费者：消费 interview:evaluate:stream，调用统一评估子图并持久化。"""

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        session_factory: async_sessionmaker[AsyncSession],
        repository: InterviewRepository,
        resume_repository: ResumeRepository,
        llm_registry: LlmProviderRegistry,
        evaluation_graph: EvaluationGraph,
    ) -> None:
        super().__init__(redis_client, config)
        self._session_factory = session_factory
        self._repository = repository
        self._resume_repository = resume_repository
        self._llm_registry = llm_registry
        self._evaluation_graph = evaluation_graph

    def task_display_name(self) -> str:
        return "面试评估"

    def parse_payload(self, msg_id: str, data: dict[bytes, bytes]) -> EvaluatePayload | None:
        raw = data.get(self._config.id_field.encode())
        if raw is None:
            logger.warning("面试评估消息缺少 %s，跳过: msgId=%s", self._config.id_field, msg_id)
            return None
        try:
            return EvaluatePayload(session_id=raw.decode())
        except (ValueError, UnicodeDecodeError):
            logger.warning("面试评估消息 %s 解析失败，跳过: msgId=%s", self._config.id_field, msg_id)
            return None

    def payload_identifier(self, payload: EvaluatePayload) -> str:
        return f"sessionId={payload.session_id}"

    def should_skip(self, payload: EvaluatePayload) -> bool:
        return False

    async def _get_session(self, session: AsyncSession, session_id: str) -> InterviewSessionORM | None:
        return await self._repository.find_by_session_id(session, session_id)

    async def mark_processing(self, payload: EvaluatePayload) -> None:
        async with self._session_factory() as session:
            orm = await self._get_session(session, payload.session_id)
            if orm is None:
                logger.warning("面试会话已删除，跳过 mark_processing: sessionId=%s", payload.session_id)
                return
            if orm.evaluate_status == AsyncTaskStatus.COMPLETED.value:
                logger.info("面试评估已完成，跳过重复处理: sessionId=%s", payload.session_id)
                return
            await self._repository.update_evaluate_status(session, orm, AsyncTaskStatus.PROCESSING.value, None)
            await session.commit()

    async def process_business(self, payload: EvaluatePayload) -> None:
        async with self._session_factory() as session:
            orm = await self._get_session(session, payload.session_id)
            if orm is None:
                logger.warning("面试会话已删除，跳过评估: sessionId=%s", payload.session_id)
                return
            if orm.evaluate_status == AsyncTaskStatus.COMPLETED.value:
                logger.info("面试评估已完成，跳过重复评估: sessionId=%s", payload.session_id)
                return

            qa_records = await self._build_qa_records(session, orm)
            resume_text = await self._load_resume_text(session, orm.resume_id)
            chat_client = await self._llm_registry.get_chat_client(self._parse_provider_id(orm.llm_provider))

            report = await self._evaluation_graph.evaluate(
                chat_client=chat_client,
                session_id=payload.session_id,
                qa_records=qa_records,
                resume_text=resume_text,
            )

            await self._persist_result(
                session, orm, report, await self._repository.find_answers_by_session_id(session, orm.id)
            )
            await session.commit()
            logger.info("面试评估结果已保存: sessionId=%s, overallScore=%s", payload.session_id, report.overall_score)

    async def _build_qa_records(self, session: AsyncSession, orm: InterviewSessionORM) -> list[QaRecord]:
        """双源合并：questions_json（题列表）+ answers 表（user_answer 权威）。"""
        questions = InterviewPersistenceService.deserialize_questions(orm.questions_json or "[]")
        answers = await self._repository.find_answers_by_session_id(session, orm.id)
        answer_map = {a.question_index: (a.user_answer or "") for a in answers}
        merged = overlay_answers(questions, answer_map)
        return build_qa_records(merged)

    async def _load_resume_text(self, session: AsyncSession, resume_id: int | None) -> str | None:
        if resume_id is None:
            return None
        resume = await self._resume_repository.get_by_id(session, resume_id)
        return resume.resume_text if resume else None

    @staticmethod
    def _parse_provider_id(llm_provider: str | None) -> int | None:
        if not llm_provider:
            return None
        try:
            return int(llm_provider)
        except ValueError:
            return None

    async def _persist_result(
        self,
        session: AsyncSession,
        orm: InterviewSessionORM,
        report: EvaluationReport,
        answers: list[InterviewAnswerORM],
    ) -> None:
        detail_map = {d.question_index: d for d in report.question_details}
        ref_map = {r.question_index: r for r in report.reference_answers}

        for answer in answers:
            detail = detail_map.get(answer.question_index)
            if detail is None:
                continue
            ref = ref_map.get(answer.question_index)
            await self._repository.update_answer_evaluation(
                session,
                answer,
                score=detail.score,
                feedback=detail.feedback,
                reference_answer=ref.reference_answer if ref else "",
                key_points_json=json.dumps(ref.key_points if ref else [], ensure_ascii=False),
            )

        await self._repository.save_evaluation_result(
            session,
            orm,
            overall_score=report.overall_score,
            overall_feedback=report.overall_feedback,
            strengths_json=json.dumps(report.strengths, ensure_ascii=False),
            improvements_json=json.dumps(report.improvements, ensure_ascii=False),
            reference_answers_json=self._serialize_reference_answers(report),
        )

    @staticmethod
    def _serialize_reference_answers(report: EvaluationReport) -> str:
        return json.dumps(
            [
                {
                    "questionIndex": r.question_index,
                    "question": r.question,
                    "referenceAnswer": r.reference_answer,
                    "keyPoints": list(r.key_points),
                }
                for r in report.reference_answers
            ],
            ensure_ascii=False,
        )

    async def mark_completed(self, payload: EvaluatePayload) -> None:
        async with self._session_factory() as session:
            orm = await self._get_session(session, payload.session_id)
            if orm is None:
                return
            await self._repository.update_evaluate_status(session, orm, AsyncTaskStatus.COMPLETED.value, None)
            await session.commit()

    async def mark_failed(self, payload: EvaluatePayload, error: str) -> None:
        async with self._session_factory() as session:
            orm = await self._get_session(session, payload.session_id)
            if orm is None:
                return
            await self._repository.update_evaluate_status(session, orm, AsyncTaskStatus.FAILED.value, error)
            await session.commit()

    async def retry_message(self, payload: EvaluatePayload, retry_count: int) -> None:
        message = {
            self._config.id_field: payload.session_id,
            FIELD_RETRY_COUNT: str(retry_count),
        }
        await self._redis.xadd(self._config.stream_key, message, max_len=STREAM_MAX_LEN)
        logger.info("面试评估任务已重新入队: sessionId=%s, retryCount=%s", payload.session_id, retry_count)
