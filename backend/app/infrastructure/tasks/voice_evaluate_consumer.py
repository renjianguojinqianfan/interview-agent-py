"""语音面试评估 Stream 消费者：消费 voice:evaluate:stream，调用统一评估子图并持久化。

公共骨架（状态机 / process_business 模板 / 重投递）见 BaseEvaluateStreamConsumer。

QaRecord 由 VoiceInterviewMessage（pair-per-row）经 voice_qa_adapter 适配而来，
category 取 InterviewPhase。评估结果写入独立的 voice_interview_evaluations 表（1:1）。
"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.evaluation import EvaluationReport, QaRecord
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
from app.infrastructure.tasks.base_evaluate_consumer import BaseEvaluateStreamConsumer
from app.infrastructure.tasks.constants import StreamConfig
from app.infrastructure.tasks.voice_evaluate_producer import VoiceEvaluatePayload

logger = logging.getLogger(__name__)


class VoiceEvaluateStreamConsumer(BaseEvaluateStreamConsumer[VoiceEvaluatePayload, VoiceInterviewSessionORM]):
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
        super().__init__(redis_client, config, session_factory, resume_repository, llm_registry, evaluation_graph)
        self._repository = repository

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

    def _session_id_text(self, payload: VoiceEvaluatePayload) -> str:
        return str(payload.session_id)

    async def _get_session_orm(
        self, session: AsyncSession, payload: VoiceEvaluatePayload
    ) -> VoiceInterviewSessionORM | None:
        return await self._repository.get_by_id(session, payload.session_id)

    def _evaluate_status(self, orm: VoiceInterviewSessionORM) -> str | None:
        return orm.evaluate_status

    def _resume_id(self, orm: VoiceInterviewSessionORM) -> int | None:
        return orm.resume_id

    def _llm_provider(self, orm: VoiceInterviewSessionORM) -> str | None:
        return orm.llm_provider

    async def _update_evaluate_status(
        self, session: AsyncSession, orm: VoiceInterviewSessionORM, status: str, error: str | None
    ) -> None:
        await self._repository.update_evaluate_status(session, orm, status, error)

    async def _build_qa_records(self, session: AsyncSession, orm: VoiceInterviewSessionORM) -> list[QaRecord]:
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

    async def _persist_result(
        self, session: AsyncSession, orm: VoiceInterviewSessionORM, report: EvaluationReport
    ) -> None:
        """写入 voice_interview_evaluations（1:1），已有行则更新。"""
        existing = await self._repository.get_evaluation_by_session(session, orm.id)
        if existing is None:
            evaluation = VoiceInterviewEvaluationORM(session_id=orm.id)
            _apply_report(evaluation, orm, report)
            await self._repository.save_evaluation(session, evaluation)
        else:
            _apply_report(existing, orm, report)


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
