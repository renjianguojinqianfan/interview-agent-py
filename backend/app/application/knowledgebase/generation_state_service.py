"""知识库题目生成状态机的事务边界（对齐 Java QuestionGenerationStateService）。

每个方法在独立 session 内以行锁（SELECT FOR UPDATE）+ taskId 匹配完成一次原子状态转换，
供 API 提交、Stream 消费者与恢复 job 三方共用；返回 False 表示任务已失效（被新任务替换），
调用方应丢弃结果。
"""

import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.knowledgebase.question_schemas import (
    QuestionGenerationConfigDTO,
    QuestionGenStatusResponse,
)
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase, KnowledgeBaseQuestion
from app.infrastructure.db.repositories.knowledge_base_question_repository import KnowledgeBaseQuestionRepository
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository

logger = logging.getLogger(__name__)

SAFE_FAILURE_MESSAGE = "题目生成失败，请稍后重试"
_ACTIVE_STATUSES = ("QUEUED", "PROCESSING")


class QuestionGenerationStateService:
    """题目生成状态机：NONE -> QUEUED -> PROCESSING -> COMPLETED / FAILED。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        kb_repository: KnowledgeBaseRepository,
        question_repository: KnowledgeBaseQuestionRepository,
    ) -> None:
        self._session_factory = session_factory
        self._kb_repository = kb_repository
        self._question_repository = question_repository

    async def create_task(self, kb_id: int, config: QuestionGenerationConfigDTO) -> QuestionGenStatusResponse:
        async with self._session_factory() as session:
            kb = await self._kb_repository.get_by_id_for_update(session, kb_id)
            if kb is None:
                raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)
            if kb.vector_status != "COMPLETED":
                raise BusinessException(ErrorCode.BAD_REQUEST, "知识库尚未完成向量化")
            if kb.question_gen_status in _ACTIVE_STATUSES:
                raise BusinessException(ErrorCode.BAD_REQUEST, "知识库问题正在生成中，请勿重复提交")

            kb.question_gen_task_id = str(uuid.uuid4())
            kb.question_gen_status = "QUEUED"
            kb.question_gen_config = config.model_dump_json(by_alias=True)
            kb.question_gen_error = None
            kb.question_gen_message = None
            kb.question_gen_saved_count = 0
            kb.question_gen_skipped_count = 0
            kb.question_gen_updated_at = datetime.now(UTC)
            await session.commit()
            return self._to_response(kb, config)

    async def get_status(self, kb_id: int) -> QuestionGenStatusResponse:
        async with self._session_factory() as session:
            kb = await self._kb_repository.get_by_id(session, kb_id)
            if kb is None:
                raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)
            return self._to_response(kb, self._read_config_or_none(kb.question_gen_config))

    async def get_config(self, kb_id: int, task_id: str) -> QuestionGenerationConfigDTO:
        async with self._session_factory() as session:
            kb = await self._kb_repository.get_by_id(session, kb_id)
            if kb is None:
                raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)
            if kb.question_gen_task_id != task_id:
                raise BusinessException(ErrorCode.BAD_REQUEST, "题目生成任务已失效")
            config = self._read_config_or_none(kb.question_gen_config)
            if config is None:
                raise BusinessException(ErrorCode.INTERNAL_ERROR, "题目生成配置不存在")
            return config

    async def try_mark_processing(self, kb_id: int, task_id: str) -> bool:
        """原子领取：QUEUED + taskId 匹配才转 PROCESSING（行锁防重复消费）。"""
        async with self._session_factory() as session:
            kb = await self._kb_repository.get_by_id_for_update(session, kb_id)
            if not self._matches(kb, task_id, "QUEUED"):
                return False
            assert kb is not None
            kb.question_gen_status = "PROCESSING"
            kb.question_gen_error = None
            kb.question_gen_updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def reset_for_retry(self, kb_id: int, task_id: str) -> bool:
        async with self._session_factory() as session:
            kb = await self._kb_repository.get_by_id_for_update(session, kb_id)
            if not self._matches(kb, task_id, "PROCESSING"):
                return False
            assert kb is not None
            kb.question_gen_status = "QUEUED"
            kb.question_gen_updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def mark_failed(self, kb_id: int, task_id: str) -> bool:
        """标记失败（对外统一安全文案）；COMPLETED 不覆盖、taskId 不匹配不触碰。"""
        async with self._session_factory() as session:
            kb = await self._kb_repository.get_by_id_for_update(session, kb_id)
            if kb is None or kb.question_gen_task_id != task_id:
                return False
            if kb.question_gen_status == "COMPLETED":
                return False
            kb.question_gen_status = "FAILED"
            kb.question_gen_error = SAFE_FAILURE_MESSAGE
            kb.question_gen_updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def replace_questions_and_complete(
        self,
        kb_id: int,
        task_id: str,
        questions: list[KnowledgeBaseQuestion],
        skipped_count: int,
    ) -> bool:
        """同一事务内整体替换旧题库并置 COMPLETED；taskId 失效时丢弃结果返回 False。"""
        async with self._session_factory() as session:
            kb = await self._kb_repository.get_by_id_for_update(session, kb_id)
            if not self._matches(kb, task_id, "PROCESSING"):
                return False
            assert kb is not None

            await self._question_repository.delete_by_knowledge_base_id(session, kb_id)
            await self._question_repository.save_all(session, questions)

            saved_count = len(questions)
            message = (
                f"已生成 {saved_count} 道题，跳过 {skipped_count} 道重复题"
                if skipped_count > 0
                else f"已生成 {saved_count} 道题"
            )
            kb.question_gen_status = "COMPLETED"
            kb.question_gen_error = None
            kb.question_gen_message = message
            kb.question_gen_saved_count = saved_count
            kb.question_gen_skipped_count = skipped_count
            kb.question_gen_updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def touch_queued_for_recovery(self, kb_id: int, task_id: str, threshold: datetime) -> bool:
        """恢复 job 重投前刷新 QUEUED 时间戳（防下轮扫描重复重投）。"""
        async with self._session_factory() as session:
            kb = await self._kb_repository.get_by_id_for_update(session, kb_id)
            if not self._matches(kb, task_id, "QUEUED"):
                return False
            assert kb is not None
            if not self._is_stale(kb.question_gen_updated_at, threshold):
                return False
            kb.question_gen_updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def reset_stale_processing(self, kb_id: int, task_id: str, threshold: datetime) -> bool:
        """卡死的 PROCESSING（执行节点崩溃）重置回 QUEUED 供重投。"""
        async with self._session_factory() as session:
            kb = await self._kb_repository.get_by_id_for_update(session, kb_id)
            if not self._matches(kb, task_id, "PROCESSING"):
                return False
            assert kb is not None
            if not self._is_stale(kb.question_gen_updated_at, threshold):
                return False
            kb.question_gen_status = "QUEUED"
            kb.question_gen_updated_at = datetime.now(UTC)
            await session.commit()
            return True

    def _matches(self, kb: KnowledgeBase | None, task_id: str, expected_status: str) -> bool:
        return kb is not None and kb.question_gen_task_id == task_id and kb.question_gen_status == expected_status

    def _is_stale(self, updated_at: datetime | None, threshold: datetime) -> bool:
        return updated_at is None or updated_at < threshold

    def _read_config_or_none(self, raw: str | None) -> QuestionGenerationConfigDTO | None:
        if raw is None or not raw.strip():
            return None
        try:
            return QuestionGenerationConfigDTO.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("解析题目生成配置失败: %s", e)
            return None

    def _to_response(self, kb: KnowledgeBase, config: QuestionGenerationConfigDTO | None) -> QuestionGenStatusResponse:
        return QuestionGenStatusResponse(
            knowledge_base_id=kb.id,
            question_gen_status=kb.question_gen_status or "NONE",
            question_gen_task_id=kb.question_gen_task_id,
            question_gen_config=config,
            saved_count=kb.question_gen_saved_count or 0,
            skipped_count=kb.question_gen_skipped_count or 0,
            message=kb.question_gen_message,
            error=kb.question_gen_error,
            updated_at=kb.question_gen_updated_at,
        )
