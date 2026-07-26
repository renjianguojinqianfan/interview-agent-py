"""知识库题库管理端点契约测试（mock 服务，镜像 tests/api/test_knowledgebase.py 风格）。"""

from collections.abc import Iterator
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_knowledge_base_question_service
from app.api.rate_limit import limiter
from app.application.knowledgebase.question_schemas import (
    CategoryCountDTO,
    KnowledgeBaseQuestionDTO,
    KnowledgeBaseQuestionFollowUpDTO,
    QuestionGenStatusResponse,
)
from app.domain.errors import BusinessException, ErrorCode
from app.main import app

client = TestClient(app)


def _question_dto(question_id: int = 11, **overrides: Any) -> KnowledgeBaseQuestionDTO:
    defaults: dict[str, Any] = {
        "id": question_id,
        "knowledge_base_id": 1,
        "knowledge_base_name": "知识库A",
        "skill_id": "knowledge-base",
        "difficulty": "mid",
        "type": "CONCEPT",
        "category": "Redis",
        "question": "什么是缓存穿透？",
        "topic_summary": "缓存三大问题",
        "reference_answer": "查询不存在的数据……",
        "key_points": ["布隆过滤器"],
        "scoring_rubric": "说出两种方案得满分",
        "follow_ups": [KnowledgeBaseQuestionFollowUpDTO(question="如何选型？")],
        "source_context": "第 3 章",
        "status": "ACTIVE",
        "created_at": datetime(2026, 7, 25, 10, 0, 0),
        "updated_at": datetime(2026, 7, 25, 11, 0, 0),
    }
    defaults.update(overrides)
    return KnowledgeBaseQuestionDTO(**defaults)


def _mock_service() -> MagicMock:
    service = MagicMock()
    service.list_questions = AsyncMock(return_value=[])
    service.list_categories = AsyncMock(return_value=[])
    service.create_question = AsyncMock()
    service.update_question = AsyncMock()
    service.update_status = AsyncMock()
    service.delete_question = AsyncMock()
    service.submit_generation_task = AsyncMock()
    service.get_generation_status = AsyncMock()
    return service


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def mock_service() -> MagicMock:
    service = _mock_service()
    app.dependency_overrides[get_knowledge_base_question_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


class TestListQuestions:
    def test_returns_camel_case_dtos(self, mock_service: MagicMock) -> None:
        mock_service.list_questions.return_value = [_question_dto()]

        resp = client.get("/api/knowledgebase/1/questions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        item = body["data"][0]
        assert item["knowledgeBaseId"] == 1
        assert item["knowledgeBaseName"] == "知识库A"
        assert item["keyPoints"] == ["布隆过滤器"]
        assert item["followUps"][0]["question"] == "如何选型？"
        assert item["createdAt"] == "2026-07-25T10:00:00"

    def test_passes_filters_to_service(self, mock_service: MagicMock) -> None:
        client.get("/api/knowledgebase/1/questions?status=DRAFT&category=Redis&difficulty=mid&keyword=cap")

        mock_service.list_questions.assert_awaited_once_with(1, "DRAFT", "Redis", "mid", "cap")

    def test_invalid_status_rejected(self, mock_service: MagicMock) -> None:
        resp = client.get("/api/knowledgebase/1/questions?status=BOGUS")

        assert resp.json()["code"] == 400


class TestListCategories:
    def test_returns_counts(self, mock_service: MagicMock) -> None:
        mock_service.list_categories.return_value = [CategoryCountDTO(category="Redis", count=5)]

        resp = client.get("/api/knowledgebase/1/questions/categories")

        assert resp.json()["data"] == [{"category": "Redis", "count": 5}]


class TestCreateQuestion:
    def test_success(self, mock_service: MagicMock) -> None:
        mock_service.create_question.return_value = _question_dto()

        resp = client.post(
            "/api/knowledgebase/1/questions",
            json={"category": "Redis", "question": "什么是缓存穿透？"},
        )

        assert resp.json()["code"] == 200
        assert resp.json()["data"]["id"] == 11

    def test_missing_required_fields_rejected(self, mock_service: MagicMock) -> None:
        resp = client.post("/api/knowledgebase/1/questions", json={"category": "Redis"})

        assert resp.json()["code"] == 400
        mock_service.create_question.assert_not_awaited()

    def test_kb_not_found(self, mock_service: MagicMock) -> None:
        mock_service.create_question.side_effect = BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)

        resp = client.post(
            "/api/knowledgebase/999/questions",
            json={"category": "Redis", "question": "题干"},
        )

        assert resp.json()["code"] == 6001


class TestUpdateQuestion:
    def test_success(self, mock_service: MagicMock) -> None:
        mock_service.update_question.return_value = _question_dto(reference_answer="新答案")

        resp = client.put("/api/knowledgebase/questions/11", json={"referenceAnswer": "新答案"})

        assert resp.json()["data"]["referenceAnswer"] == "新答案"

    def test_question_not_found(self, mock_service: MagicMock) -> None:
        mock_service.update_question.side_effect = BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND)

        resp = client.put("/api/knowledgebase/questions/999", json={})

        assert resp.json()["code"] == 3003


class TestUpdateQuestionStatus:
    def test_success(self, mock_service: MagicMock) -> None:
        mock_service.update_status.return_value = _question_dto(status="ACTIVE")

        resp = client.put("/api/knowledgebase/questions/11/status", json={"status": "ACTIVE"})

        assert resp.json()["data"]["status"] == "ACTIVE"
        mock_service.update_status.assert_awaited_once_with(11, "ACTIVE")

    def test_invalid_status_rejected(self, mock_service: MagicMock) -> None:
        resp = client.put("/api/knowledgebase/questions/11/status", json={"status": "BOGUS"})

        assert resp.json()["code"] == 400
        mock_service.update_status.assert_not_awaited()

    def test_question_not_found(self, mock_service: MagicMock) -> None:
        mock_service.update_status.side_effect = BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND)

        resp = client.put("/api/knowledgebase/questions/999/status", json={"status": "ACTIVE"})

        assert resp.json()["code"] == 3003


class TestDeleteQuestion:
    def test_success(self, mock_service: MagicMock) -> None:
        resp = client.delete("/api/knowledgebase/questions/11")

        assert resp.json()["code"] == 200
        mock_service.delete_question.assert_awaited_once_with(11)

    def test_question_not_found(self, mock_service: MagicMock) -> None:
        mock_service.delete_question.side_effect = BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND)

        resp = client.delete("/api/knowledgebase/questions/999")

        assert resp.json()["code"] == 3003


def _gen_status(**overrides: Any) -> QuestionGenStatusResponse:
    defaults: dict[str, Any] = {
        "knowledge_base_id": 1,
        "question_gen_status": "QUEUED",
        "question_gen_task_id": "task-1",
    }
    defaults.update(overrides)
    return QuestionGenStatusResponse(**defaults)


class TestGenerateQuestions:
    def test_success_returns_queued_status(self, mock_service: MagicMock) -> None:
        mock_service.submit_generation_task.return_value = _gen_status()

        resp = client.post(
            "/api/knowledgebase/1/questions/generate",
            json={"questionCount": 10, "followUpCount": 2, "categoryLimit": 3},
        )

        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["questionGenStatus"] == "QUEUED"
        assert body["data"]["questionGenTaskId"] == "task-1"

    def test_validation_rejects_out_of_range(self, mock_service: MagicMock) -> None:
        cases = [
            {"questionCount": 0, "categoryLimit": 3},  # 题量越界
            {"questionCount": 31, "categoryLimit": 3},
            {"questionCount": 10, "categoryLimit": 6},  # 方向数越界
            {"questionCount": 10},  # 方向数缺失
            {"questionCount": 10, "categoryLimit": 3, "difficulty": "expert"},  # 非法难度
            {"questionCount": 10, "categoryLimit": 3, "followUpCount": 6},  # 追问越界
        ]
        for body in cases:
            limiter.reset()
            resp = client.post("/api/knowledgebase/1/questions/generate", json=body)
            assert resp.json()["code"] == 400, body
        mock_service.submit_generation_task.assert_not_awaited()

    def test_duplicate_submission_maps_business_error(self, mock_service: MagicMock) -> None:
        mock_service.submit_generation_task.side_effect = BusinessException(
            ErrorCode.BAD_REQUEST, "知识库问题正在生成中，请勿重复提交"
        )

        resp = client.post(
            "/api/knowledgebase/1/questions/generate",
            json={"questionCount": 10, "categoryLimit": 3},
        )

        assert resp.json()["code"] == 400
        assert "请勿重复提交" in resp.json()["message"]

    def test_rate_limit_blocks_third_request(self, mock_service: MagicMock) -> None:
        mock_service.submit_generation_task.return_value = _gen_status()

        codes: list[int] = []
        for _ in range(3):
            resp = client.post(
                "/api/knowledgebase/1/questions/generate",
                json={"questionCount": 10, "categoryLimit": 3},
            )
            codes.append(resp.json()["code"])

        assert codes[:2] == [200, 200]
        assert codes[2] == ErrorCode.RATE_LIMIT_EXCEEDED.code


class TestGenerationStatus:
    def test_returns_full_state_machine_fields(self, mock_service: MagicMock) -> None:
        mock_service.get_generation_status.return_value = _gen_status(
            question_gen_status="COMPLETED",
            saved_count=8,
            skipped_count=2,
            message="已生成 8 道题，跳过 2 道重复题",
            updated_at=datetime(2026, 7, 26, 12, 0, 0),
        )

        resp = client.get("/api/knowledgebase/1/questions/generation-status")

        data = resp.json()["data"]
        assert data["questionGenStatus"] == "COMPLETED"
        assert data["savedCount"] == 8
        assert data["skippedCount"] == 2
        assert data["message"] == "已生成 8 道题，跳过 2 道重复题"
        assert data["updatedAt"] == "2026-07-26T12:00:00"

    def test_kb_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_generation_status.side_effect = BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)

        resp = client.get("/api/knowledgebase/999/questions/generation-status")

        assert resp.json()["code"] == 6001
