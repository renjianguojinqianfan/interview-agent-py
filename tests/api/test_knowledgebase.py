from collections.abc import Iterator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_knowledge_base_service
from app.api.rate_limit import limiter
from app.application.knowledgebase.schemas import (
    KnowledgeBaseDetailDTO,
    KnowledgeBaseInfoDTO,
    KnowledgeBaseListItemDTO,
    KnowledgeBasePageDTO,
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


def _page_dto() -> KnowledgeBasePageDTO:
    return KnowledgeBasePageDTO(
        items=[
            KnowledgeBaseListItemDTO(
                id=1,
                filename="doc.pdf",
                file_size=2048,
                uploaded_at=datetime(2026, 7, 20, 10, 0, 0),
                chunk_count=0,
                vector_status="PENDING",
                vector_error=None,
                vectorized_at=None,
            )
        ],
        total=1,
        page=1,
        size=10,
    )


def _detail_dto() -> KnowledgeBaseDetailDTO:
    return KnowledgeBaseDetailDTO(
        id=1,
        filename="doc.pdf",
        file_size=2048,
        content_type="application/pdf",
        storage_url="http://localhost:9000/bucket/key",
        uploaded_at=datetime(2026, 7, 20, 10, 0, 0),
        content_text="知识库正文",
        chunk_count=3,
        vector_status="COMPLETED",
        vector_error=None,
        vectorized_at=datetime(2026, 7, 20, 10, 5, 0),
    )


def _mock_service() -> MagicMock:
    service = MagicMock()
    service.upload = AsyncMock()
    service.list_knowledge_bases = AsyncMock()
    service.get_detail = AsyncMock()
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
            "/api/knowledge-bases/upload",
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["duplicate"] is False
        assert body["data"]["knowledgeBase"]["id"] == 7
        assert body["data"]["knowledgeBase"]["vectorStatus"] == "PENDING"
        assert body["data"]["storage"]["knowledgeBaseId"] == 7

    def test_duplicate_returns_existing(self, mock_service: MagicMock) -> None:
        mock_service.upload.return_value = _upload_response(kb_id=3, duplicate=True)

        response = client.post(
            "/api/knowledge-bases/upload",
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.json()["data"]["duplicate"] is True

    def test_unsupported_type_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.upload.side_effect = BusinessException(ErrorCode.KNOWLEDGE_BASE_UPLOAD_FAILED)

        response = client.post(
            "/api/knowledge-bases/upload",
            files={"file": ("x.bin", b"fake", "application/octet-stream")},
        )

        assert response.json()["code"] == ErrorCode.KNOWLEDGE_BASE_UPLOAD_FAILED.code

    def test_rate_limit_blocks_fourth_request(self, mock_service: MagicMock) -> None:
        mock_service.upload.return_value = _upload_response(kb_id=1)

        codes: list[int] = []
        for _ in range(4):
            response = client.post(
                "/api/knowledge-bases/upload",
                files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )
            codes.append(response.json()["code"])

        assert codes[:3] == [200, 200, 200]
        assert codes[3] == ErrorCode.RATE_LIMIT_EXCEEDED.code


class TestList:
    def test_returns_paginated_list(self, mock_service: MagicMock) -> None:
        mock_service.list_knowledge_bases.return_value = _page_dto()

        response = client.get("/api/knowledge-bases?page=1&size=10")

        body = response.json()
        assert body["code"] == 200
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["vectorStatus"] == "PENDING"

    def test_uses_default_pagination(self, mock_service: MagicMock) -> None:
        mock_service.list_knowledge_bases.return_value = _page_dto()

        client.get("/api/knowledge-bases")

        mock_service.list_knowledge_bases.assert_awaited_once_with(page=1, size=10)


class TestGetDetail:
    def test_returns_detail(self, mock_service: MagicMock) -> None:
        mock_service.get_detail.return_value = _detail_dto()

        response = client.get("/api/knowledge-bases/1/detail")

        body = response.json()
        assert body["code"] == 200
        assert body["data"]["chunkCount"] == 3
        assert body["data"]["vectorStatus"] == "COMPLETED"

    def test_not_found_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.get_detail.side_effect = BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)

        response = client.get("/api/knowledge-bases/999/detail")

        assert response.json()["code"] == ErrorCode.KNOWLEDGE_BASE_NOT_FOUND.code


class TestDelete:
    def test_deletes_successfully(self, mock_service: MagicMock) -> None:
        mock_service.delete.return_value = None

        response = client.delete("/api/knowledge-bases/1")

        body = response.json()
        assert body["code"] == 200
        assert body["data"] is None

    def test_not_found_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.delete.side_effect = BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)

        response = client.delete("/api/knowledge-bases/999")

        assert response.json()["code"] == ErrorCode.KNOWLEDGE_BASE_NOT_FOUND.code


class TestRevectorize:
    def test_triggers_successfully(self, mock_service: MagicMock) -> None:
        mock_service.revectorize.return_value = None

        response = client.post("/api/knowledge-bases/1/revectorize")

        assert response.json()["code"] == 200
        mock_service.revectorize.assert_awaited_once_with(1)

    def test_rate_limit_blocks_third_request(self, mock_service: MagicMock) -> None:
        mock_service.revectorize.return_value = None

        codes: list[int] = []
        for _ in range(3):
            response = client.post("/api/knowledge-bases/1/revectorize")
            codes.append(response.json()["code"])

        assert codes[:2] == [200, 200]
        assert codes[2] == ErrorCode.RATE_LIMIT_EXCEEDED.code
