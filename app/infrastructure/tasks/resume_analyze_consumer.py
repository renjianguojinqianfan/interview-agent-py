import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.resume.analysis import ResumeAnalysisResult, ResumeAnalysisService
from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.models.resume import Resume, ResumeAnalysis
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_consumer import BaseStreamConsumer
from app.infrastructure.tasks.constants import FIELD_RETRY_COUNT, STREAM_MAX_LEN, StreamConfig
from app.infrastructure.tasks.resume_analyze_producer import ResumeAnalyzePayload

logger = logging.getLogger(__name__)


class AnalyzeStreamConsumer(BaseStreamConsumer[ResumeAnalyzePayload]):
    """简历分析 Stream 消费者：消费 resume:analyze:stream，调用 LLM 评分并持久化。

    幂等策略：should_skip 恒 False（同步方法无法做异步 DB 检查）；
    幂等下沉到 mark_processing（COMPLETED 不转 PROCESSING）与 process_business（COMPLETED/已删除跳过）。
    """

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        session_factory: async_sessionmaker[AsyncSession],
        repository: ResumeRepository,
        analysis_service: ResumeAnalysisService,
    ) -> None:
        super().__init__(redis_client, config)
        self._session_factory = session_factory
        self._repository = repository
        self._analysis_service = analysis_service

    def task_display_name(self) -> str:
        return "简历分析"

    def parse_payload(self, msg_id: str, data: dict[bytes, bytes]) -> ResumeAnalyzePayload | None:
        raw = data.get(self._config.id_field.encode())
        if raw is None:
            logger.warning("简历分析消息缺少 %s，跳过: msgId=%s", self._config.id_field, msg_id)
            return None
        try:
            return ResumeAnalyzePayload(resume_id=int(raw))
        except (ValueError, TypeError):
            logger.warning("简历分析消息 %s 解析失败，跳过: msgId=%s", self._config.id_field, msg_id)
            return None

    def payload_identifier(self, payload: ResumeAnalyzePayload) -> str:
        return f"resumeId={payload.resume_id}"

    def should_skip(self, payload: ResumeAnalyzePayload) -> bool:
        return False

    async def _get_resume(self, session: AsyncSession, resume_id: int) -> Resume | None:
        return await self._repository.get_by_id(session, resume_id)

    async def mark_processing(self, payload: ResumeAnalyzePayload) -> None:
        async with self._session_factory() as session:
            resume = await self._get_resume(session, payload.resume_id)
            if resume is None:
                logger.warning("简历已删除，跳过 mark_processing: resumeId=%s", payload.resume_id)
                return
            if resume.analyze_status == AsyncTaskStatus.COMPLETED.value:
                logger.info("简历已分析完成，跳过重复处理: resumeId=%s", payload.resume_id)
                return
            await self._repository.update_analyze_status(session, resume, AsyncTaskStatus.PROCESSING.value, None)
            await session.commit()

    async def process_business(self, payload: ResumeAnalyzePayload) -> None:
        async with self._session_factory() as session:
            resume = await self._get_resume(session, payload.resume_id)
            if resume is None:
                logger.warning("简历已删除，跳过分析: resumeId=%s", payload.resume_id)
                return
            if resume.analyze_status == AsyncTaskStatus.COMPLETED.value:
                logger.info("简历已分析完成，跳过重复评分: resumeId=%s", payload.resume_id)
                return

            result = await self._analysis_service.analyze_resume(resume.resume_text or "")
            await self._repository.delete_analyses_by_resume_id(session, payload.resume_id)
            analysis = self._to_analysis_entity(payload.resume_id, result)
            await self._repository.save_analysis(session, analysis)
            await session.commit()
            logger.info("简历分析结果已保存: resumeId=%s, score=%s", payload.resume_id, result.overallScore)

    async def mark_completed(self, payload: ResumeAnalyzePayload) -> None:
        async with self._session_factory() as session:
            resume = await self._get_resume(session, payload.resume_id)
            if resume is None:
                return
            await self._repository.update_analyze_status(session, resume, AsyncTaskStatus.COMPLETED.value, None)
            await session.commit()

    async def mark_failed(self, payload: ResumeAnalyzePayload, error: str) -> None:
        async with self._session_factory() as session:
            resume = await self._get_resume(session, payload.resume_id)
            if resume is None:
                return
            await self._repository.update_analyze_status(session, resume, AsyncTaskStatus.FAILED.value, error)
            await session.commit()

    async def retry_message(self, payload: ResumeAnalyzePayload, retry_count: int) -> None:
        message = {
            self._config.id_field: str(payload.resume_id),
            FIELD_RETRY_COUNT: str(retry_count),
        }
        await self._redis.xadd(self._config.stream_key, message, max_len=STREAM_MAX_LEN)
        logger.info("简历分析任务已重新入队: resumeId=%s, retryCount=%s", payload.resume_id, retry_count)

    def _to_analysis_entity(self, resume_id: int, result: ResumeAnalysisResult) -> ResumeAnalysis:
        return ResumeAnalysis(
            resume_id=resume_id,
            overall_score=result.overallScore,
            content_score=result.scoreDetail.contentScore,
            structure_score=result.scoreDetail.structureScore,
            skill_match_score=result.scoreDetail.skillMatchScore,
            expression_score=result.scoreDetail.expressionScore,
            project_score=result.scoreDetail.projectScore,
            summary=result.summary,
            strengths_json=json.dumps(result.strengths, ensure_ascii=False),
            suggestions_json=json.dumps([s.model_dump() for s in result.suggestions], ensure_ascii=False),
        )
