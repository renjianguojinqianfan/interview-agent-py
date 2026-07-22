from collections.abc import Iterator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_knowledge_base_service
from app.api.rate_limit import limiter
from app.application.knowledgebase.schemas import (
    KnowledgeBaseInfoDTO,
    KnowledgeBaseListItemDTO,
    KnowledgeBaseStatsDTO,
    KnowledgeBaseUploadResponse,
    StorageInfoDTO,
)
from app.domain.errors import BusinessException, ErrorCode
from app.main import app

client = TestClient(app)


def _upload_response(kb_id: int = 1, duplicate: bool = False) -> KnowledgeBaseUploadResponse:
    return KnowledgeBaseUploadResponse(
        knowledge_base=KnowledgeBaseInfoDTO(id=kb_id, filename="doc.pdf", vector_status="PENDING"),
        storage=StorageInfoDTO(
            file_key="knowledge-bases/2026/07/20/uuid_doc.pdf",
            file_url="http://localhost:9000/bucket/knowledge-bases/2026/07/20/uuid_doc.pdf",
            knowledge_base_id=kb_id,
        ),
        duplicate=duplicate,
    )


def _list_item(kb_id: int = 1) -> KnowledgeBaseListItemDTO:
    return KnowledgeBaseListItemDTO(
        id=kb_id,
        name="知识库A",
        category="后端",
        original_filename="doc.pdf",
        file_size=2048,
        content_type="application/pdf",
        uploaded_at=datetime(2026, 7, 20, 10, 0, 0),
        last_accessed_at=datetime(2026, 7, 20, 10, 0, 0),
        access_count=4,
        question_count=2,
        vector_status="COMPLETED",
        vector_error=None,
        chunk_count=3,
    )


def _stats() -> KnowledgeBaseStatsDTO:
    return KnowledgeBaseStatsDTO(
        total_count=5,
        total_question_count=7,
        total_access_count=12,
        completed_count=3,
        processing_count=1,
    )


def _mock_service() -> MagicMock:
    service = MagicMock()
    service.upload = AsyncMock()
    service.list_knowledge_bases = AsyncMock()
    service.list_by_category = AsyncMock()
    service.list_categories = AsyncMock()
    service.search = AsyncMock()
    service.update_category = AsyncMock()
    service.get_statistics = AsyncMock()
    service.download = AsyncMock()
    service.delete = AsyncMock()
    service.revectorize = AsyncMock()
    return service


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def mock_service() -> Iterator[MagicMock]:
    service = _mock_service()
    app.dependency_overrides[get_knowledge_base_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_knowledge_base_service, None)


class TestUpload:
    def test_returns_kb_id_and_pending_status(self, mock_service: MagicMock) -> None:
        mock_service.upload.return_value = _upload_response(kb_id=7)

        response = client.post(
            "/api/knowledgebase/upload",
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["duplicate"] is False
        assert body["data"]["knowledgeBase"]["id"] == 7
        assert body["data"]["storage"]["knowledgeBaseId"] == 7

    def test_passes_name_and_category(self, mock_service: MagicMock) -> None:
        mock_service.upload.return_value = _upload_response(kb_id=1)

        client.post(
            "/api/knowledgebase/upload",
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"name": "自定义名", "category": "后端"},
        )

        args = mock_service.upload.call_args
        assert args.kwargs["name"] == "自定义名"
        assert args.kwargs["category"] == "后端"

    def test_rate_limit_blocks_fourth_request(self, mock_service: MagicMock) -> None:
        mock_service.upload.return_value = _upload_response(kb_id=1)

        codes: list[int] = []
        for _ in range(4):
            response = client.post(
                "/api/knowledgebase/upload",
                files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )
            codes.append(response.json()["code"])

        assert codes[:3] == [200, 200, 200]
        assert codes[3] == ErrorCode.RATE_LIMIT_EXCEEDED.code


class TestList:
    def test_returns_bare_array_with_contract_fields(self, mock_service: MagicMock) -> None:
        mock_service.list_knowledge_bases.return_value = [_list_item(1)]

        response = client.get("/api/knowledgebase/list?sortBy=size&vectorStatus=COMPLETED")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["data"], list)
        item = body["data"][0]
        assert item["id"] == 1
        assert item["name"] == "知识库A"
        assert item["category"] == "后端"
        assert item["originalFilename"] == "doc.pdf"
        assert item["accessCount"] == 4
        assert item["questionCount"] == 2
        assert item["vectorStatus"] == "COMPLETED"

    def test_passes_sort_and_status(self, mock_service: MagicMock) -> None:
        mock_service.list_knowledge_bases.return_value = []

        client.get("/api/knowledgebase/list?sortBy=access&vectorStatus=PENDING")

        mock_service.list_knowledge_bases.assert_awaited_once_with(sort_by="access", vector_status="PENDING")


class TestStats:
    def test_returns_stats(self, mock_service: MagicMock) -> None:
        mock_service.get_statistics.return_value = _stats()

        response = client.get("/api/knowledgebase/stats")

        body = response.json()
        assert body["data"]["totalCount"] == 5
        assert body["data"]["totalQuestionCount"] == 7
        assert body["data"]["totalAccessCount"] == 12
        assert body["data"]["completedCount"] == 3
        assert body["data"]["processingCount"] == 1


class TestCategories:
    def test_list_categories(self, mock_service: MagicMock) -> None:
        mock_service.list_categories.return_value = ["后端", "前端"]

        response = client.get("/api/knowledgebase/categories")

        assert response.json()["data"] == ["后端", "前端"]

    def test_list_by_category(self, mock_service: MagicMock) -> None:
        mock_service.list_by_category.return_value = [_list_item(1)]

        response = client.get("/api/knowledgebase/category/后端")

        assert response.status_code == 200
        assert response.json()["data"][0]["category"] == "后端"
        mock_service.list_by_category.assert_awaited_once_with("后端")

    def test_update_category(self, mock_service: MagicMock) -> None:
        mock_service.update_category.return_value = None

        response = client.put("/api/knowledgebase/1/category", json={"category": "后端"})

        assert response.status_code == 200
        assert response.json()["code"] == 200
        mock_service.update_category.assert_awaited_once_with(1, "后端")


class TestSearch:
    def test_search(self, mock_service: MagicMock) -> None:
        mock_service.search.return_value = [_list_item(1)]

        response = client.get("/api/knowledgebase/search?keyword=python")

        assert response.status_code == 200
        assert response.json()["data"][0]["id"] == 1
        mock_service.search.assert_awaited_once_with("python")


class TestDownload:
    def test_returns_file_bytes(self, mock_service: MagicMock) -> None:
        mock_service.download.return_value = (b"filebytes", "doc.pdf", "application/pdf")

        response = client.get("/api/knowledgebase/1/download")

        assert response.status_code == 200
        assert response.content == b"filebytes"
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers["content-disposition"]

    def test_not_found_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.download.side_effect = BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)

        response = client.get("/api/knowledgebase/999/download")

        assert response.json()["code"] == ErrorCode.KNOWLEDGE_BASE_NOT_FOUND.code


class TestDelete:
    def test_deletes_successfully(self, mock_service: MagicMock) -> None:
        mock_service.delete.return_value = None

        response = client.delete("/api/knowledgebase/1")

        body = response.json()
        assert body["code"] == 200
        assert body["data"] is None

    def test_not_found_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.delete.side_effect = BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)

        response = client.delete("/api/knowledgebase/999")

        assert response.json()["code"] == ErrorCode.KNOWLEDGE_BASE_NOT_FOUND.code


class TestRevectorize:
    def test_triggers_successfully(self, mock_service: MagicMock) -> None:
        mock_service.revectorize.return_value = None

        response = client.post("/api/knowledgebase/1/revectorize")

        assert response.json()["code"] == 200
        mock_service.revectorize.assert_awaited_once_with(1)

    def test_rate_limit_blocks_third_request(self, mock_service: MagicMock) -> None:
        mock_service.revectorize.return_value = None

        codes: list[int] = []
        for _ in range(3):
            response = client.post("/api/knowledgebase/1/revectorize")
            codes.append(response.json()["code"])

        assert codes[:2] == [200, 200]
        assert codes[2] == ErrorCode.RATE_LIMIT_EXCEEDED.code
