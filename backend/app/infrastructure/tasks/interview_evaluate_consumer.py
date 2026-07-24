"""面试评估 Stream 消费者：消费 interview:evaluate:stream，调用统一评估子图并持久化。

公共骨架（状态机 / process_business 模板 / 重投递）见 BaseEvaluateStreamConsumer。

QaRecord 双源合并：questions_json 提供完整题列表（question/category，userAnswer 恒 None），
interview_answers 表提供权威 user_answer（DB questions_json 不回写 user_answer）。
"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.evaluation import EvaluationReport, QaRecord
from app.domain.services.evaluation import build_qa_records, overlay_answers
from app.domain.services.question_codec import deserialize_questions
from app.graphs.evaluation import EvaluationGraph
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM
from app.infrastructure.db.repositories.interview_repository import InterviewRepository
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_evaluate_consumer import BaseEvaluateStreamConsumer
from app.infrastructure.tasks.constants import StreamConfig
from app.infrastructure.tasks.interview_evaluate_producer import EvaluatePayload

logger = logging.getLogger(__name__)


class EvaluateStreamConsumer(BaseEvaluateStreamConsumer[EvaluatePayload, InterviewSessionORM]):
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
        super().__init__(redis_client, config, session_factory, resume_repository, llm_registry, evaluation_graph)
        self._repository = repository

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

    def _session_id_text(self, payload: EvaluatePayload) -> str:
        return payload.session_id

    async def _get_session_orm(self, session: AsyncSession, payload: EvaluatePayload) -> InterviewSessionORM | None:
        return await self._repository.find_by_session_id(session, payload.session_id)

    def _evaluate_status(self, orm: InterviewSessionORM) -> str | None:
        return orm.evaluate_status

    def _resume_id(self, orm: InterviewSessionORM) -> int | None:
        return orm.resume_id

    def _llm_provider(self, orm: InterviewSessionORM) -> str | None:
        return orm.llm_provider

    async def _update_evaluate_status(
        self, session: AsyncSession, orm: InterviewSessionORM, status: str, error: str | None
    ) -> None:
        await self._repository.update_evaluate_status(session, orm, status, error)

    async def _build_qa_records(self, session: AsyncSession, orm: InterviewSessionORM) -> list[QaRecord]:
        """双源合并：questions_json（题列表）+ answers 表（user_answer 权威）。"""
        questions = deserialize_questions(orm.questions_json or "[]")
        answers = await self._repository.find_answers_by_session_id(session, orm.id)
        answer_map = {a.question_index: (a.user_answer or "") for a in answers}
        merged = overlay_answers(questions, answer_map)
        return build_qa_records(merged)

    async def _persist_result(self, session: AsyncSession, orm: InterviewSessionORM, report: EvaluationReport) -> None:
        answers = await self._repository.find_answers_by_session_id(session, orm.id)
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

        await self._repository.save_evaluation_result(session, orm, report=report)
