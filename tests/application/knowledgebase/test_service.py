from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.knowledgebase.service import KnowledgeBaseService
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase

_ALLOWED = ["application/pdf", "text/plain", "text/markdown"]
_MAX_SIZE = 10 * 1024 * 1024


def _make_service(**mocks: Any) -> tuple[KnowledgeBaseService, dict[str, Any]]:
    session = mocks.get("session") or AsyncMock()

    repository = mocks.get("repository") or MagicMock()
    repository.find_by_hash = mocks.get("find_by_hash") or AsyncMock(return_value=None)
    repository.get_by_id = mocks.get("get_by_id") or AsyncMock(return_value=None)
    repository.update_vector_status = AsyncMock()
    repository.delete = AsyncMock()
    repository.list_paginated = AsyncMock(return_value=([], 0))

    async def _save(_session: Any, kb: KnowledgeBase) -> KnowledgeBase:
        kb.id = 1
        return kb

    repository.save = AsyncMock(side_effect=_save)

    parser = MagicMock()
    parser.parse_content = MagicMock(return_value=mocks.get("parsed_text", "知识库正文"))

    hash_service = MagicMock()
    hash_service.calculate_hash = MagicMock(return_value="hash123")

    content_detector = MagicMock()
    content_detector.detect = MagicMock(return_value=mocks.get("detected_type", "application/pdf"))

    storage = MagicMock()
    storage.upload_file = AsyncMock(return_value="knowledge-bases/2026/07/20/uuid_doc.pdf")
    storage.build_file_url = MagicMock(return_value="http://minio/bucket/key")
    storage.delete_file = AsyncMock()

    producer = MagicMock()
    producer.send_task = AsyncMock(return_value="100-0")

    vector_repository = MagicMock()
    vector_repository.delete_by_knowledge_base_id = AsyncMock(return_value=0)

    service = KnowledgeBaseService(
        session=session,
        repository=repository,
        parser=parser,
        hash_service=hash_service,
        content_detector=content_detector,
        storage=storage,
        producer=producer,
        vector_repository=vector_repository,
        allowed_types=_ALLOWED,
        max_file_size=_MAX_SIZE,
    )
    return service, {
        "session": session,
        "repository": repository,
        "storage": storage,
        "producer": producer,
        "vector_repository": vector_repository,
    }


class TestUpload:
    async def test_happy_path_saves_and_enqueues(self) -> None:
        service, m = _make_service()

        result = await service.upload("doc.pdf", "application/pdf", b"data")

        assert result.duplicate is False
        assert result.knowledge_base.id == 1
        m["repository"].save.assert_awaited_once()
        m["session"].commit.assert_awaited()
        m["producer"].send_task.assert_awaited_once()

    async def test_duplicate_short_circuits(self) -> None:
        existing = KnowledgeBase(
            id=5,
            file_hash="hash123",
            original_filename="doc.pdf",
            storage_key="k",
            storage_url="u",
            vector_status="COMPLETED",
        )
        service, m = _make_service(find_by_hash=AsyncMock(return_value=existing))

        result = await service.upload("doc.pdf", "application/pdf", b"data")

        assert result.duplicate is True
        assert result.knowledge_base.id == 5
        m["repository"].save.assert_not_awaited()
        m["producer"].send_task.assert_not_awaited()

    async def test_empty_text_raises_parse_failed(self) -> None:
        service, _ = _make_service(parsed_text="   ")

        with pytest.raises(BusinessException) as exc:
            await service.upload("doc.pdf", "application/pdf", b"data")

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_PARSE_FAILED

    async def test_unsupported_type_raises_upload_failed(self) -> None:
        service, _ = _make_service(detected_type="application/octet-stream")

        with pytest.raises(BusinessException) as exc:
            await service.upload("x.bin", "application/octet-stream", b"data")

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_UPLOAD_FAILED

    async def test_oversize_raises_upload_failed(self) -> None:
        service, _ = _make_service()

        with pytest.raises(BusinessException) as exc:
            await service.upload("doc.pdf", "application/pdf", b"x" * (_MAX_SIZE + 1))

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_UPLOAD_FAILED


class TestDelete:
    async def test_deletes_storage_vectors_and_row(self) -> None:
        kb = KnowledgeBase(id=1, file_hash="h", original_filename="doc.pdf", storage_key="k", vector_status="COMPLETED")
        service, m = _make_service(get_by_id=AsyncMock(return_value=kb))

        await service.delete(1)

        m["storage"].delete_file.assert_awaited_once_with("k")
        m["vector_repository"].delete_by_knowledge_base_id.assert_awaited_once()
        m["repository"].delete.assert_awaited_once()
        m["session"].commit.assert_awaited()

    async def test_not_found_raises(self) -> None:
        service, _ = _make_service(get_by_id=AsyncMock(return_value=None))

        with pytest.raises(BusinessException) as exc:
            await service.delete(999)

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_NOT_FOUND


class TestRevectorize:
    async def test_resets_status_and_enqueues(self) -> None:
        kb = KnowledgeBase(id=1, file_hash="h", original_filename="doc.pdf", vector_status="COMPLETED")
        service, m = _make_service(get_by_id=AsyncMock(return_value=kb))

        await service.revectorize(1)

        m["repository"].update_vector_status.assert_awaited_once()
        assert m["repository"].update_vector_status.call_args.args[2] == "PENDING"
        m["producer"].send_task.assert_awaited_once()

    async def test_not_found_raises(self) -> None:
        service, _ = _make_service(get_by_id=AsyncMock(return_value=None))

        with pytest.raises(BusinessException) as exc:
            await service.revectorize(999)

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_NOT_FOUND


class TestGetDetail:
    async def test_not_found_raises(self) -> None:
        service, _ = _make_service(get_by_id=AsyncMock(return_value=None))

        with pytest.raises(BusinessException) as exc:
            await service.get_detail(999)

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_NOT_FOUND
