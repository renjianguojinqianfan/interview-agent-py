"""评估 Stream 消费者基类：抽取文字/语音评估消费者的公共骨架。

两个评估消费者（interview / voice）曾共享 ~80 行近乎逐字重复的逻辑：简历文本加载、
provider_id 解析、状态机（mark_processing/completed/failed）、process_business 模板、
retry 重投递。本基类上移这些公共实现，子类仅实现领域差异钩子（session 查找、
sessionId 文本化、状态字段读取、状态更新、QaRecord 构建、结果持久化）。

会话 ORM 以未约束类型参数 S 表示：文字/语音会话列均为 SQLAlchemy Mapped[...]，
mypy 无法对其做 Protocol 结构匹配，故公共骨架经 _evaluate_status/_resume_id/
_llm_provider 访问钩子读取字段，而非直接访问属性。

依赖方向：infrastructure -> domain（QaRecord/EvaluationReport/AsyncTaskStatus）
+ graphs（统一评估子图）。
"""

import logging
from abc import abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.evaluation import EvaluationReport, QaRecord
from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.errors import BusinessException
from app.graphs.evaluation import EvaluationGraph
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_consumer import BaseStreamConsumer
from app.infrastructure.tasks.constants import FIELD_RETRY_COUNT, STREAM_MAX_LEN, StreamConfig

logger = logging.getLogger(__name__)


class BaseEvaluateStreamConsumer[P, S](BaseStreamConsumer[P]):
    """评估 Stream 消费者基类：编排公共骨架，子类实现领域差异钩子。

    幂等策略（两子类一致）：should_skip 恒 False（继承基类默认）；幂等下沉到
    mark_processing（COMPLETED 不转 PROCESSING）与 process_business（COMPLETED/已删除跳过）。
    """

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        session_factory: async_sessionmaker[AsyncSession],
        resume_repository: ResumeRepository,
        llm_registry: LlmProviderRegistry,
        evaluation_graph: EvaluationGraph,
    ) -> None:
        super().__init__(redis_client, config)
        self._session_factory = session_factory
        self._resume_repository = resume_repository
        self._llm_registry = llm_registry
        self._evaluation_graph = evaluation_graph

    # ==================== 公共实现 ====================

    def payload_identifier(self, payload: P) -> str:
        return f"sessionId={self._session_id_text(payload)}"

    async def mark_processing(self, payload: P) -> None:
        async with self._session_factory() as session:
            orm = await self._get_session_orm(session, payload)
            if orm is None:
                logger.warning(
                    "%s会话已删除，跳过 mark_processing: %s", self.task_display_name(), self.payload_identifier(payload)
                )
                return
            if self._evaluate_status(orm) == AsyncTaskStatus.COMPLETED.value:
                logger.info("%s已完成，跳过重复处理: %s", self.task_display_name(), self.payload_identifier(payload))
                return
            await self._update_evaluate_status(session, orm, AsyncTaskStatus.PROCESSING.value, None)
            await session.commit()

    async def process_business(self, payload: P) -> None:
        async with self._session_factory() as session:
            orm = await self._get_session_orm(session, payload)
            if orm is None:
                logger.warning("%s会话已删除，跳过评估: %s", self.task_display_name(), self.payload_identifier(payload))
                return
            if self._evaluate_status(orm) == AsyncTaskStatus.COMPLETED.value:
                logger.info("%s已完成，跳过重复评估: %s", self.task_display_name(), self.payload_identifier(payload))
                return

            qa_records = await self._build_qa_records(session, orm)
            resume_text = await self._load_resume_text(session, self._resume_id(orm))
            chat_client = await self._llm_registry.get_chat_client(
                await self._resolve_provider_id(self._llm_provider(orm))
            )

            report = await self._evaluation_graph.evaluate(
                chat_client=chat_client,
                session_id=self._session_id_text(payload),
                qa_records=qa_records,
                resume_text=resume_text,
            )

            await self._persist_result(session, orm, report)
            await session.commit()
            logger.info(
                "%s结果已保存: %s, overallScore=%s",
                self.task_display_name(),
                self.payload_identifier(payload),
                report.overall_score,
            )

    async def mark_completed(self, payload: P) -> None:
        async with self._session_factory() as session:
            orm = await self._get_session_orm(session, payload)
            if orm is None:
                return
            await self._update_evaluate_status(session, orm, AsyncTaskStatus.COMPLETED.value, None)
            await session.commit()

    async def mark_failed(self, payload: P, error: str) -> None:
        async with self._session_factory() as session:
            orm = await self._get_session_orm(session, payload)
            if orm is None:
                return
            await self._update_evaluate_status(session, orm, AsyncTaskStatus.FAILED.value, error)
            await session.commit()

    async def retry_message(self, payload: P, retry_count: int) -> None:
        message = {
            self._config.id_field: self._session_id_text(payload),
            FIELD_RETRY_COUNT: str(retry_count),
        }
        await self._redis.xadd(self._config.stream_key, message, max_len=STREAM_MAX_LEN)
        logger.info(
            "%s任务已重新入队: %s, retryCount=%s",
            self.task_display_name(),
            self.payload_identifier(payload),
            retry_count,
        )

    async def _load_resume_text(self, session: AsyncSession, resume_id: int | None) -> str | None:
        if resume_id is None:
            return None
        resume = await self._resume_repository.get_by_id(session, resume_id)
        return resume.resume_text if resume else None

    async def _resolve_provider_id(self, llm_provider: str | None) -> int | None:
        """按名解析会话使用的供应商（ADR-0015 字符串标识）；已删除/无效则回退默认。

        后台评估不因供应商失效而崩溃（区别于创建请求的非静默报错）。
        """
        try:
            return await self._llm_registry.resolve_provider_id_by_name(llm_provider)
        except BusinessException:
            logger.warning(
                "%s会话的 LLM Provider 已不存在，回退默认: %s",
                self.task_display_name(),
                llm_provider,
            )
            return None

    # ==================== 领域差异钩子 ====================

    @abstractmethod
    def _session_id_text(self, payload: P) -> str:
        """payload 的 sessionId 文本形式（用于日志 / 重投递消息 / 子图 session_id）。"""

    @abstractmethod
    async def _get_session_orm(self, session: AsyncSession, payload: P) -> S | None:
        """按 payload 查找会话 ORM（find_by_session_id vs get_by_id）。"""

    @abstractmethod
    def _evaluate_status(self, orm: S) -> str | None:
        """读取会话评估状态字段（S 为 SQLAlchemy 模型，无法经 Protocol 统一访问）。"""

    @abstractmethod
    def _resume_id(self, orm: S) -> int | None:
        """读取会话关联的 resume_id。"""

    @abstractmethod
    def _llm_provider(self, orm: S) -> str | None:
        """读取会话指定的 llm_provider。"""

    @abstractmethod
    async def _update_evaluate_status(self, session: AsyncSession, orm: S, status: str, error: str | None) -> None:
        """更新会话评估状态（委托各自仓储）。"""

    @abstractmethod
    async def _build_qa_records(self, session: AsyncSession, orm: S) -> list[QaRecord]:
        """构建评估用 QaRecord 列表（领域差异：双源合并 vs 语音消息适配）。"""

    @abstractmethod
    async def _persist_result(self, session: AsyncSession, orm: S, report: EvaluationReport) -> None:
        """持久化评估结果（领域差异：answers 回写 vs 1:1 评估行）。"""
