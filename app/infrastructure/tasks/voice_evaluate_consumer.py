"""语音面试评估 Stream 消费者：消费 voice:evaluate:stream，调用统一评估子图并持久化。

幂等策略与文字评估一致：should_skip 恒 False；幂等下沉到 mark_processing
（COMPLETED 不转 PROCESSING）与 process_business（COMPLETED/已删除跳过）。

QaRecord 由 VoiceInterviewMessage（pair-per-row）经 voice_qa_adapter 适配而来，
category 取 InterviewPhase。评估结果写入独立的 voice_interview_evaluations 表（1:1）。
"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.evaluation import EvaluationReport, QaRecord
from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.entities.voice_interview import VoiceMessage
from app.domain.services.voice_qa_adapter import build_voice_qa_records
from app.graphs.evaluation import EvaluationGraph
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewEvaluation as VoiceInterviewEvaluationORM,
)
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewSession as VoiceInterviewSessionORM,
)
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.db.repositories.voice_interview_repository import VoiceInterviewRepository
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_consumer import BaseStreamConsumer
from app.infrastructure.tasks.constants import FIELD_RETRY_COUNT, STREAM_MAX_LEN, StreamConfig
from app.infrastructure.tasks.voice_evaluate_producer import VoiceEvaluatePayload

logger = logging.getLogger(__name__)


class VoiceEvaluateStreamConsumer(BaseStreamConsumer[VoiceEvaluatePayload]):
    """语音面试评估 Stream 消费者：消费 voice:evaluate:stream，调用统一评估子图并持久化。"""

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        session_factory: async_sessionmaker[AsyncSession],
        repository: VoiceInterviewRepository,
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
        return "语音面试评估"

    def parse_payload(self, msg_id: str, data: dict[bytes, bytes]) -> VoiceEvaluatePayload | None:
        raw = data.get(self._config.id_field.encode())
        if raw is None:
            logger.warning("语音评估消息缺少 %s，跳过: msgId=%s", self._config.id_field, msg_id)
            return None
        try:
            return VoiceEvaluatePayload(session_id=int(raw.decode()))
        except (ValueError, UnicodeDecodeError):
            logger.warning("语音评估消息 %s 解析失败，跳过: msgId=%s", self._config.id_field, msg_id)
            return None

    def payload_identifier(self, payload: VoiceEvaluatePayload) -> str:
        return f"sessionId={payload.session_id}"

    def should_skip(self, payload: VoiceEvaluatePayload) -> bool:
        return False

    async def mark_processing(self, payload: VoiceEvaluatePayload) -> None:
        async with self._session_factory() as session:
            orm = await self._repository.get_by_id(session, payload.session_id)
            if orm is None:
                logger.warning("语音会话已删除，跳过 mark_processing: sessionId=%s", payload.session_id)
                return
            if orm.evaluate_status == AsyncTaskStatus.COMPLETED.value:
                logger.info("语音评估已完成，跳过重复处理: sessionId=%s", payload.session_id)
                return
            await self._repository.update_evaluate_status(session, orm, AsyncTaskStatus.PROCESSING.value, None)
            await session.commit()

    async def process_business(self, payload: VoiceEvaluatePayload) -> None:
        async with self._session_factory() as session:
            orm = await self._repository.get_by_id(session, payload.session_id)
            if orm is None:
                logger.warning("语音会话已删除，跳过评估: sessionId=%s", payload.session_id)
                return
            if orm.evaluate_status == AsyncTaskStatus.COMPLETED.value:
                logger.info("语音评估已完成，跳过重复评估: sessionId=%s", payload.session_id)
                return

            qa_records = await self._build_qa_records(session, orm)
            resume_text = await self._load_resume_text(session, orm.resume_id)
            chat_client = await self._llm_registry.get_chat_client(self._parse_provider_id(orm.llm_provider))

            report = await self._evaluation_graph.evaluate(
                chat_client=chat_client,
                session_id=str(payload.session_id),
                qa_records=qa_records,
                resume_text=resume_text,
            )

            await self._persist_result(session, orm, report)
            await session.commit()
            logger.info(
                "语音评估结果已保存: sessionId=%s, overallScore=%s",
                payload.session_id,
                report.overall_score,
            )

    async def _build_qa_records(
        self,
        session: AsyncSession,
        orm: VoiceInterviewSessionORM,
    ) -> list[QaRecord]:
        """从 VoiceInterviewMessage 行适配为 QaRecord（category=phase）。"""
        messages = await self._repository.find_messages_by_session(session, orm.id)
        voice_messages = [
            VoiceMessage(
                sequence_num=m.sequence_num,
                phase=m.phase,
                ai_generated_text=m.ai_generated_text,
                user_recognized_text=m.user_recognized_text,
            )
            for m in messages
        ]
        return build_voice_qa_records(voice_messages)

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
        orm: VoiceInterviewSessionORM,
        report: EvaluationReport,
    ) -> None:
        """写入 voice_interview_evaluations（1:1），已有行则更新。"""
        existing = await self._repository.get_evaluation_by_session(session, orm.id)
        if existing is None:
            evaluation = VoiceInterviewEvaluationORM(session_id=orm.id)
            _apply_report(evaluation, orm, report)
            await self._repository.save_evaluation(session, evaluation)
        else:
            _apply_report(existing, orm, report)

    async def mark_completed(self, payload: VoiceEvaluatePayload) -> None:
        async with self._session_factory() as session:
            orm = await self._repository.get_by_id(session, payload.session_id)
            if orm is None:
                return
            await self._repository.update_evaluate_status(session, orm, AsyncTaskStatus.COMPLETED.value, None)
            await session.commit()

    async def mark_failed(self, payload: VoiceEvaluatePayload, error: str) -> None:
        async with self._session_factory() as session:
            orm = await self._repository.get_by_id(session, payload.session_id)
            if orm is None:
                return
            await self._repository.update_evaluate_status(session, orm, AsyncTaskStatus.FAILED.value, error)
            await session.commit()

    async def retry_message(self, payload: VoiceEvaluatePayload, retry_count: int) -> None:
        message = {
            self._config.id_field: str(payload.session_id),
            FIELD_RETRY_COUNT: str(retry_count),
        }
        await self._redis.xadd(self._config.stream_key, message, max_len=STREAM_MAX_LEN)
        logger.info("语音评估任务已重新入队: sessionId=%s, retryCount=%s", payload.session_id, retry_count)


def _apply_report(
    evaluation: VoiceInterviewEvaluationORM,
    orm: VoiceInterviewSessionORM,
    report: EvaluationReport,
) -> None:
    """将评估报告字段写入 ORM 行（insert 与 update 共用）。"""
    evaluation.overall_score = report.overall_score
    evaluation.overall_feedback = report.overall_feedback
    evaluation.question_evaluations_json = _serialize_question_details(report)
    evaluation.strengths_json = json.dumps(report.strengths, ensure_ascii=False)
    evaluation.improvements_json = json.dumps(report.improvements, ensure_ascii=False)
    evaluation.reference_answers_json = _serialize_reference_answers(report)
    evaluation.interviewer_role = orm.role_type
    evaluation.interview_date = orm.start_time


def _serialize_question_details(report: EvaluationReport) -> str:
    return json.dumps(
        [
            {
                "questionIndex": d.question_index,
                "question": d.question,
                "category": d.category,
                "userAnswer": d.user_answer,
                "score": d.score,
                "feedback": d.feedback,
            }
            for d in report.question_details
        ],
        ensure_ascii=False,
    )


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
