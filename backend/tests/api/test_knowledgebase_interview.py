"""知识库题库管理端点契约测试（mock 服务，镜像 tests/api/test_knowledgebase.py 风格）。"""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_knowledge_base_question_service
from app.application.knowledgebase.question_schemas import (
    CategoryCountDTO,
    KnowledgeBaseQuestionDTO,
    KnowledgeBaseQuestionFollowUpDTO,
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
    return service


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
