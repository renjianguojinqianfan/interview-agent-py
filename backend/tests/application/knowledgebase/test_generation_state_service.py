"""QuestionGenerationStateService 单元测试（mock 仓储 + session_factory，事务语义靠竖切验证）。"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.knowledgebase.generation_state_service import (
    SAFE_FAILURE_MESSAGE,
    QuestionGenerationStateService,
)
from app.application.knowledgebase.question_schemas import QuestionGenerationConfigDTO
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase, KnowledgeBaseQuestion


def _make_kb(**overrides: Any) -> KnowledgeBase:
    defaults: dict[str, Any] = {
        "id": 1,
        "file_hash": "hash123",
        "original_filename": "doc.pdf",
        "name": "知识库A",
        "vector_status": "COMPLETED",
        "question_gen_status": "NONE",
    }
    defaults.update(overrides)
    return KnowledgeBase(**defaults)


def _config(**overrides: Any) -> QuestionGenerationConfigDTO:
    defaults: dict[str, Any] = {
        "difficulty": "mid",
        "question_count": 10,
        "follow_up_count": 2,
        "category_limit": 3,
        "llm_provider": None,
    }
    defaults.update(overrides)
    return QuestionGenerationConfigDTO(**defaults)


class _FakeSessionFactory:
    """模拟 async_sessionmaker：factory() 返回 async context manager，yield 同一个 session mock。"""

    def __init__(self) -> None:
        self.session = AsyncMock()

    def __call__(self) -> Any:
        factory = self

        class _Ctx:
            async def __aenter__(self) -> Any:
                return factory.session

            async def __aexit__(self, *args: Any) -> None:
                return None

        return _Ctx()


def _make_service(kb: KnowledgeBase | None) -> tuple[QuestionGenerationStateService, dict[str, Any]]:
    session_factory = _FakeSessionFactory()

    kb_repository = MagicMock()
    kb_repository.get_by_id_for_update = AsyncMock(return_value=kb)
    kb_repository.get_by_id = AsyncMock(return_value=kb)

    question_repository = MagicMock()
    question_repository.delete_by_knowledge_base_id = AsyncMock()
    question_repository.save_all = AsyncMock()

    service = QuestionGenerationStateService(
        session_factory=session_factory,  # type: ignore[arg-type]
        kb_repository=kb_repository,
        question_repository=question_repository,
    )
    return service, {
        "session": session_factory.session,
        "kb_repository": kb_repository,
        "question_repository": question_repository,
    }


class TestCreateTask:
    async def test_writes_queued_state_with_task_id_and_config_snapshot(self) -> None:
        kb = _make_kb()
        service, mocks = _make_service(kb)

        response = await service.create_task(1, _config())

        assert kb.question_gen_status == "QUEUED"
        assert kb.question_gen_task_id is not None and len(kb.question_gen_task_id) == 36
        assert json.loads(kb.question_gen_config)["questionCount"] == 10
        assert kb.question_gen_error is None
        assert kb.question_gen_message is None
        assert kb.question_gen_saved_count == 0
        assert kb.question_gen_skipped_count == 0
        assert kb.question_gen_updated_at is not None
        assert response.question_gen_status == "QUEUED"
        assert response.question_gen_task_id == kb.question_gen_task_id
        assert response.question_gen_config is not None
        assert response.question_gen_config.question_count == 10
        mocks["session"].commit.assert_awaited_once()

    async def test_rejects_when_not_vectorized(self) -> None:
        service, _ = _make_service(_make_kb(vector_status="PROCESSING"))

        with pytest.raises(BusinessException) as exc:
            await service.create_task(1, _config())
        assert exc.value.error_code == ErrorCode.BAD_REQUEST
        assert "尚未完成向量化" in exc.value.message

    @pytest.mark.parametrize("active_status", ["QUEUED", "PROCESSING"])
    async def test_rejects_duplicate_submission_when_active(self, active_status: str) -> None:
        service, _ = _make_service(_make_kb(question_gen_status=active_status))

        with pytest.raises(BusinessException) as exc:
            await service.create_task(1, _config())
        assert exc.value.error_code == ErrorCode.BAD_REQUEST
        assert "请勿重复提交" in exc.value.message

    async def test_kb_not_found(self) -> None:
        service, _ = _make_service(None)

        with pytest.raises(BusinessException) as exc:
            await service.create_task(999, _config())
        assert exc.value.error_code == ErrorCode.KNOWLEDGE_BASE_NOT_FOUND


class TestGetStatus:
    async def test_none_status_defaults(self) -> None:
        kb = _make_kb()
        kb.question_gen_status = None  # type: ignore[assignment]  # 未 flush 的存量行
        service, _ = _make_service(kb)

        response = await service.get_status(1)

        assert response.question_gen_status == "NONE"
        assert response.saved_count == 0
        assert response.skipped_count == 0
        assert response.question_gen_config is None

    async def test_parses_config_snapshot(self) -> None:
        kb = _make_kb(
            question_gen_status="COMPLETED",
            question_gen_config=json.dumps(
                {
                    "difficulty": "senior",
                    "questionCount": 5,
                    "followUpCount": 1,
                    "categoryLimit": 2,
                    "llmProvider": None,
                }
            ),
            question_gen_saved_count=5,
        )
        service, _ = _make_service(kb)

        response = await service.get_status(1)

        assert response.question_gen_config is not None
        assert response.question_gen_config.difficulty == "senior"
        assert response.saved_count == 5

    async def test_kb_not_found(self) -> None:
        service, _ = _make_service(None)

        with pytest.raises(BusinessException) as exc:
            await service.get_status(999)
        assert exc.value.error_code == ErrorCode.KNOWLEDGE_BASE_NOT_FOUND


class TestGetConfig:
    async def test_returns_config_when_task_matches(self) -> None:
        kb = _make_kb(
            question_gen_task_id="task-1",
            question_gen_config=json.dumps(
                {
                    "difficulty": "mid",
                    "questionCount": 10,
                    "followUpCount": 2,
                    "categoryLimit": 3,
                    "llmProvider": "qwen",
                }
            ),
        )
        service, _ = _make_service(kb)

        config = await service.get_config(1, "task-1")

        assert config.llm_provider == "qwen"

    async def test_stale_task_id_rejected(self) -> None:
        service, _ = _make_service(_make_kb(question_gen_task_id="task-new"))

        with pytest.raises(BusinessException) as exc:
            await service.get_config(1, "task-old")
        assert exc.value.error_code == ErrorCode.BAD_REQUEST


class TestTryMarkProcessing:
    async def test_claims_queued_task(self) -> None:
        kb = _make_kb(question_gen_status="QUEUED", question_gen_task_id="task-1")
        service, mocks = _make_service(kb)

        assert await service.try_mark_processing(1, "task-1") is True
        assert kb.question_gen_status == "PROCESSING"
        assert kb.question_gen_error is None
        mocks["session"].commit.assert_awaited_once()

    async def test_rejects_task_id_mismatch(self) -> None:
        kb = _make_kb(question_gen_status="QUEUED", question_gen_task_id="task-new")
        service, _ = _make_service(kb)

        assert await service.try_mark_processing(1, "task-old") is False
        assert kb.question_gen_status == "QUEUED"

    async def test_rejects_non_queued_status(self) -> None:
        kb = _make_kb(question_gen_status="PROCESSING", question_gen_task_id="task-1")
        service, _ = _make_service(kb)

        assert await service.try_mark_processing(1, "task-1") is False

    async def test_rejects_missing_kb(self) -> None:
        service, _ = _make_service(None)

        assert await service.try_mark_processing(999, "task-1") is False


class TestMarkFailed:
    async def test_marks_failed_with_safe_message(self) -> None:
        kb = _make_kb(question_gen_status="PROCESSING", question_gen_task_id="task-1")
        service, _ = _make_service(kb)

        assert await service.mark_failed(1, "task-1") is True
        assert kb.question_gen_status == "FAILED"
        assert kb.question_gen_error == SAFE_FAILURE_MESSAGE

    async def test_completed_not_overwritten(self) -> None:
        kb = _make_kb(question_gen_status="COMPLETED", question_gen_task_id="task-1")
        service, _ = _make_service(kb)

        assert await service.mark_failed(1, "task-1") is False
        assert kb.question_gen_status == "COMPLETED"

    async def test_task_id_mismatch_returns_false(self) -> None:
        kb = _make_kb(question_gen_status="PROCESSING", question_gen_task_id="task-new")
        service, _ = _make_service(kb)

        assert await service.mark_failed(1, "task-old") is False


class TestReplaceQuestionsAndComplete:
    def _questions(self, count: int) -> list[KnowledgeBaseQuestion]:
        return [KnowledgeBaseQuestion(knowledge_base_id=1, question=f"题{i}") for i in range(count)]

    async def test_replaces_and_completes_with_skip_message(self) -> None:
        kb = _make_kb(question_gen_status="PROCESSING", question_gen_task_id="task-1")
        service, mocks = _make_service(kb)

        ok = await service.replace_questions_and_complete(1, "task-1", self._questions(3), skipped_count=2)

        assert ok is True
        mocks["question_repository"].delete_by_knowledge_base_id.assert_awaited_once()
        mocks["question_repository"].save_all.assert_awaited_once()
        assert kb.question_gen_status == "COMPLETED"
        assert kb.question_gen_error is None
        assert kb.question_gen_message == "已生成 3 道题，跳过 2 道重复题"
        assert kb.question_gen_saved_count == 3
        assert kb.question_gen_skipped_count == 2

    async def test_message_without_skipped(self) -> None:
        kb = _make_kb(question_gen_status="PROCESSING", question_gen_task_id="task-1")
        service, _ = _make_service(kb)

        await service.replace_questions_and_complete(1, "task-1", self._questions(5), skipped_count=0)

        assert kb.question_gen_message == "已生成 5 道题"

    async def test_stale_task_discards_result(self) -> None:
        kb = _make_kb(question_gen_status="PROCESSING", question_gen_task_id="task-new")
        service, mocks = _make_service(kb)

        ok = await service.replace_questions_and_complete(1, "task-old", self._questions(3), skipped_count=0)

        assert ok is False
        mocks["question_repository"].delete_by_knowledge_base_id.assert_not_awaited()
        mocks["question_repository"].save_all.assert_not_awaited()


class TestRecoveryTransitions:
    def _stale_time(self) -> datetime:
        return datetime.now(UTC) - timedelta(minutes=30)

    async def test_reset_for_retry_processing_back_to_queued(self) -> None:
        kb = _make_kb(question_gen_status="PROCESSING", question_gen_task_id="task-1")
        service, _ = _make_service(kb)

        assert await service.reset_for_retry(1, "task-1") is True
        assert kb.question_gen_status == "QUEUED"

    async def test_touch_queued_for_recovery_only_when_stale(self) -> None:
        threshold = datetime.now(UTC) - timedelta(minutes=2)
        stale_kb = _make_kb(
            question_gen_status="QUEUED", question_gen_task_id="task-1", question_gen_updated_at=self._stale_time()
        )
        service, _ = _make_service(stale_kb)
        assert await service.touch_queued_for_recovery(1, "task-1", threshold) is True

        fresh_kb = _make_kb(
            question_gen_status="QUEUED", question_gen_task_id="task-1", question_gen_updated_at=datetime.now(UTC)
        )
        service, _ = _make_service(fresh_kb)
        assert await service.touch_queued_for_recovery(1, "task-1", threshold) is False

    async def test_reset_stale_processing_back_to_queued(self) -> None:
        threshold = datetime.now(UTC) - timedelta(minutes=20)
        kb = _make_kb(
            question_gen_status="PROCESSING", question_gen_task_id="task-1", question_gen_updated_at=self._stale_time()
        )
        service, _ = _make_service(kb)

        assert await service.reset_stale_processing(1, "task-1", threshold) is True
        assert kb.question_gen_status == "QUEUED"

    async def test_null_updated_at_treated_as_stale(self) -> None:
        threshold = datetime.now(UTC) - timedelta(minutes=2)
        kb = _make_kb(question_gen_status="QUEUED", question_gen_task_id="task-1", question_gen_updated_at=None)
        service, _ = _make_service(kb)

        assert await service.touch_queued_for_recovery(1, "task-1", threshold) is True
