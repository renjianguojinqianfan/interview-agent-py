from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.knowledgebase.schemas import KnowledgeBaseStatsDTO
from app.application.knowledgebase.service import KnowledgeBaseService
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase

_ALLOWED = ["application/pdf", "text/plain", "text/markdown"]
_MAX_SIZE = 10 * 1024 * 1024


def _make_kb(**overrides: Any) -> KnowledgeBase:
    defaults: dict[str, Any] = {
        "id": 1,
        "file_hash": "h",
        "original_filename": "doc.pdf",
        "name": "知识库A",
        "category": "后端",
        "file_size": 2048,
        "content_type": "application/pdf",
        "storage_key": "k",
        "storage_url": "u",
        "content_text": "正文",
        "chunk_count": 3,
        "access_count": 4,
        "question_count": 2,
        "vector_status": "COMPLETED",
        "vector_error": None,
        "uploaded_at": datetime(2026, 7, 20, 10, 0, 0),
        "last_accessed_at": None,
    }
    defaults.update(overrides)
    return KnowledgeBase(**defaults)


def _make_service(**mocks: Any) -> tuple[KnowledgeBaseService, dict[str, Any]]:
    session = mocks.get("session") or AsyncMock()

    repository = mocks.get("repository") or MagicMock()
    repository.find_by_hash = mocks.get("find_by_hash") or AsyncMock(return_value=None)
    repository.get_by_id = mocks.get("get_by_id") or AsyncMock(return_value=None)
    repository.update_vector_status = AsyncMock()
    repository.update_category = AsyncMock()
    repository.delete = AsyncMock()
    repository.list_all = AsyncMock(return_value=[])
    repository.list_by_category = AsyncMock(return_value=[])
    repository.list_categories = AsyncMock(return_value=[])
    repository.search = AsyncMock(return_value=[])
    repository.count_all = AsyncMock(return_value=0)
    repository.sum_access_count = AsyncMock(return_value=0)
    repository.count_by_vector_status = AsyncMock(return_value=0)

    async def _save(_session: Any, kb: KnowledgeBase) -> KnowledgeBase:
        kb.id = 1
        return kb

    repository.save = AsyncMock(side_effect=_save)

    rag_repository = MagicMock()
    rag_repository.count_messages_by_role = AsyncMock(return_value=0)

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
    storage.download_file = AsyncMock(return_value=b"filebytes")

    producer = MagicMock()
    producer.send_task = AsyncMock(return_value="100-0")

    vector_repository = MagicMock()
    vector_repository.delete_by_knowledge_base_id = AsyncMock(return_value=0)

    service = KnowledgeBaseService(
        session=session,
        repository=repository,
        rag_repository=rag_repository,
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
        "rag_repository": rag_repository,
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

    async def test_persists_name_and_category(self) -> None:
        captured: list[KnowledgeBase] = []

        async def _save(_session: Any, kb: KnowledgeBase) -> KnowledgeBase:
            kb.id = 1
            captured.append(kb)
            return kb

        service, m = _make_service()
        m["repository"].save.side_effect = _save

        await service.upload("doc.pdf", "application/pdf", b"data", name="自定义名", category="后端")

        assert captured[0].name == "自定义名"
        assert captured[0].category == "后端"

    async def test_name_defaults_to_filename(self) -> None:
        captured: list[KnowledgeBase] = []

        async def _save(_session: Any, kb: KnowledgeBase) -> KnowledgeBase:
            kb.id = 1
            captured.append(kb)
            return kb

        service, m = _make_service()
        m["repository"].save.side_effect = _save

        await service.upload("doc.pdf", "application/pdf", b"data")

        assert captured[0].name == "doc.pdf"
        assert captured[0].category is None

    async def test_duplicate_short_circuits(self) -> None:
        existing = _make_kb(id=5, vector_status="COMPLETED")
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


class TestListKnowledgeBases:
    async def test_returns_bare_list_with_contract_fields(self) -> None:
        service, m = _make_service()
        m["repository"].list_all.return_value = [_make_kb(id=1, name="知识库A", category="后端")]

        result = await service.list_knowledge_bases()

        assert isinstance(result, list)
        assert result[0].id == 1
        assert result[0].name == "知识库A"
        assert result[0].category == "后端"
        assert result[0].original_filename == "doc.pdf"
        assert result[0].access_count == 4
        assert result[0].question_count == 2

    async def test_name_falls_back_to_filename(self) -> None:
        service, m = _make_service()
        m["repository"].list_all.return_value = [_make_kb(name=None)]

        result = await service.list_knowledge_bases()

        assert result[0].name == "doc.pdf"

    async def test_last_accessed_falls_back_to_uploaded(self) -> None:
        service, m = _make_service()
        m["repository"].list_all.return_value = [_make_kb(last_accessed_at=None)]

        result = await service.list_knowledge_bases()

        assert result[0].last_accessed_at == datetime(2026, 7, 20, 10, 0, 0)

    async def test_sort_by_size_desc(self) -> None:
        service, m = _make_service()
        m["repository"].list_all.return_value = [
            _make_kb(id=1, file_size=100),
            _make_kb(id=2, file_size=500),
            _make_kb(id=3, file_size=300),
        ]

        result = await service.list_knowledge_bases(sort_by="size")

        assert [r.id for r in result] == [2, 3, 1]

    async def test_passes_vector_status_filter(self) -> None:
        service, m = _make_service()

        await service.list_knowledge_bases(vector_status="COMPLETED")

        m["repository"].list_all.assert_awaited_once_with(service._session, "COMPLETED")


class TestCategories:
    async def test_list_categories(self) -> None:
        service, m = _make_service()
        m["repository"].list_categories.return_value = ["后端", "前端"]

        assert await service.list_categories() == ["后端", "前端"]

    async def test_list_by_category(self) -> None:
        service, m = _make_service()
        m["repository"].list_by_category.return_value = [_make_kb(category="后端")]

        result = await service.list_by_category("后端")

        assert result[0].category == "后端"
        m["repository"].list_by_category.assert_awaited_once_with(service._session, "后端")

    async def test_update_category_commits(self) -> None:
        service, m = _make_service(get_by_id=AsyncMock(return_value=_make_kb()))

        await service.update_category(1, "  ")  # 空白归一为 None

        m["repository"].update_category.assert_awaited_once()
        assert m["repository"].update_category.call_args.args[2] is None
        m["session"].commit.assert_awaited()

    async def test_update_category_not_found_raises(self) -> None:
        service, _ = _make_service(get_by_id=AsyncMock(return_value=None))

        with pytest.raises(BusinessException) as exc:
            await service.update_category(999, "后端")

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_NOT_FOUND


class TestSearch:
    async def test_search_delegates_trimmed_keyword(self) -> None:
        service, m = _make_service()
        m["repository"].search.return_value = [_make_kb()]

        result = await service.search("  python  ")

        assert len(result) == 1
        m["repository"].search.assert_awaited_once_with(service._session, "python")

    async def test_blank_keyword_returns_full_list(self) -> None:
        service, m = _make_service()
        m["repository"].list_all.return_value = [_make_kb()]

        result = await service.search("   ")

        assert len(result) == 1
        m["repository"].search.assert_not_awaited()


class TestStatistics:
    async def test_aggregates_counts(self) -> None:
        service, m = _make_service()
        m["repository"].count_all.return_value = 5
        m["repository"].sum_access_count.return_value = 12
        m["repository"].count_by_vector_status.side_effect = [3, 1]  # COMPLETED, PROCESSING
        m["rag_repository"].count_messages_by_role.return_value = 7

        result = await service.get_statistics()

        assert isinstance(result, KnowledgeBaseStatsDTO)
        assert result.total_count == 5
        assert result.total_access_count == 12
        assert result.completed_count == 3
        assert result.processing_count == 1
        assert result.total_question_count == 7
        m["rag_repository"].count_messages_by_role.assert_awaited_once_with(service._session, "user")


class TestDownload:
    async def test_returns_bytes_filename_content_type(self) -> None:
        service, m = _make_service(get_by_id=AsyncMock(return_value=_make_kb(storage_key="k")))

        data, filename, content_type = await service.download(1)

        assert data == b"filebytes"
        assert filename == "doc.pdf"
        assert content_type == "application/pdf"
        m["storage"].download_file.assert_awaited_once_with("k")

    async def test_not_found_raises(self) -> None:
        service, _ = _make_service(get_by_id=AsyncMock(return_value=None))

        with pytest.raises(BusinessException) as exc:
            await service.download(999)

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_NOT_FOUND

    async def test_missing_storage_key_raises(self) -> None:
        service, _ = _make_service(get_by_id=AsyncMock(return_value=_make_kb(storage_key=None)))

        with pytest.raises(BusinessException) as exc:
            await service.download(1)

        assert exc.value.error_code is ErrorCode.STORAGE_DOWNLOAD_FAILED


class TestDelete:
    async def test_deletes_storage_vectors_and_row(self) -> None:
        service, m = _make_service(get_by_id=AsyncMock(return_value=_make_kb(storage_key="k")))

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
        service, m = _make_service(get_by_id=AsyncMock(return_value=_make_kb(vector_status="COMPLETED")))

        await service.revectorize(1)

        m["repository"].update_vector_status.assert_awaited_once()
        assert m["repository"].update_vector_status.call_args.args[2] == "PENDING"
        m["producer"].send_task.assert_awaited_once()

    async def test_not_found_raises(self) -> None:
        service, _ = _make_service(get_by_id=AsyncMock(return_value=None))

        with pytest.raises(BusinessException) as exc:
            await service.revectorize(999)

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_NOT_FOUND
