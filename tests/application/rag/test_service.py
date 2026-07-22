import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest

from app.application.rag.service import RagChatService, RagConfig
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase
from app.infrastructure.db.models.rag_chat import RagChatSession
from app.infrastructure.vector.repository import SearchResult

_CONFIG = RagConfig(
    min_score=0.3,
    probe_window=120,
    query_rewrite_enabled=False,
    max_context_chars=6000,
    history_limit=10,
)


def _make_session(**overrides: Any) -> RagChatSession:
    defaults: dict[str, Any] = {
        "id": 1,
        "session_id": "sess-abc",
        "knowledge_base_ids_json": json.dumps([1, 2]),
        "title": "会话",
        "status": "ACTIVE",
        "pinned": False,
        "created_at": datetime(2026, 7, 20, 10, 0, 0),
        "updated_at": datetime(2026, 7, 20, 10, 0, 0),
    }
    defaults.update(overrides)
    return RagChatSession(**defaults)


def _make_kb(**overrides: Any) -> KnowledgeBase:
    defaults: dict[str, Any] = {
        "id": 1,
        "file_hash": "h",
        "original_filename": "doc.pdf",
        "name": "知识库A",
        "category": None,
        "file_size": 100,
        "content_type": "application/pdf",
        "storage_key": "k",
        "storage_url": "u",
        "content_text": "t",
        "chunk_count": 1,
        "access_count": 0,
        "question_count": 0,
        "vector_status": "COMPLETED",
        "vector_error": None,
        "uploaded_at": datetime(2026, 7, 20, 10, 0, 0),
        "last_accessed_at": None,
    }
    defaults.update(overrides)
    return KnowledgeBase(**defaults)


def _make_factory() -> MagicMock:
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


async def _astream(tokens: list[str]) -> Any:
    for token in tokens:
        yield SimpleNamespace(content=token)


_ERR_REQUEST = httpx.Request("POST", "https://dashscope.example/api")


async def _astream_then_raise(exc: BaseException, tokens: list[str] | None = None) -> Any:
    for token in tokens or []:
        yield SimpleNamespace(content=token)
    raise exc


def _make_service(**over: Any) -> tuple[RagChatService, dict[str, Any]]:
    session = over.get("session") or AsyncMock()
    repository = MagicMock()
    repository.get_by_id = over.get("get_by_id") or AsyncMock(return_value=_make_session())
    repository.list_all = AsyncMock(return_value=[])
    repository.count_messages = AsyncMock(return_value=0)
    repository.list_messages = AsyncMock(return_value=[])
    repository.recent_history = AsyncMock(return_value=[])
    repository.add_message = AsyncMock()
    repository.delete = AsyncMock()
    repository.update_pinned = AsyncMock()
    repository.update_title = AsyncMock()

    async def _save(_s: Any, entity: RagChatSession) -> RagChatSession:
        entity.id = 1
        entity.created_at = datetime(2026, 7, 20, 10, 0, 0)
        entity.updated_at = datetime(2026, 7, 20, 10, 0, 0)
        return entity

    repository.save = AsyncMock(side_effect=_save)

    kb_repository = MagicMock()
    kb_repository.get_by_id = over.get("kb_get_by_id") or AsyncMock(return_value=_make_kb())

    vector_repository = MagicMock()
    vector_repository.search = over.get("search") or AsyncMock(return_value=[SearchResult("片段A", 0.9, 1)])

    embeddings = MagicMock()
    embeddings.aembed_documents = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    chat = MagicMock()
    chat.ainvoke = AsyncMock(return_value=SimpleNamespace(content="这是基于知识库的答案"))
    chat.astream = MagicMock(return_value=_astream(["这是", "答案"]))
    llm_registry = MagicMock()
    llm_registry.get_default_embeddings = AsyncMock(return_value=embeddings)
    llm_registry.get_chat_client = AsyncMock(return_value=chat)
    llm_registry.get_streaming_chat_client = AsyncMock(return_value=chat)

    service = RagChatService(
        session=session,
        session_factory=_make_factory(),
        repository=repository,
        kb_repository=kb_repository,
        vector_repository=vector_repository,
        llm_registry=llm_registry,
        config=over.get("config") or _CONFIG,
    )
    return service, {
        "session": session,
        "repository": repository,
        "kb_repository": kb_repository,
        "vector_repository": vector_repository,
        "chat": chat,
    }


class TestCreateSession:
    async def test_creates_and_returns_dto(self) -> None:
        service, m = _make_service()
        dto = await service.create_session([1, 2], "标题")
        assert dto.id == 1
        assert dto.title == "标题"
        assert dto.knowledge_base_ids == [1, 2]
        m["repository"].save.assert_awaited_once()
        m["session"].commit.assert_awaited()

    async def test_empty_kb_ids_raises_bad_request(self) -> None:
        service, _ = _make_service()
        with pytest.raises(BusinessException) as exc:
            await service.create_session([], None)
        assert exc.value.error_code is ErrorCode.BAD_REQUEST

    async def test_missing_kb_raises_not_found(self) -> None:
        service, _ = _make_service(kb_get_by_id=AsyncMock(return_value=None))
        with pytest.raises(BusinessException) as exc:
            await service.create_session([99], None)
        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_NOT_FOUND


class TestListSessions:
    async def test_returns_bare_list_with_contract_fields(self) -> None:
        service, m = _make_service()
        m["repository"].list_all.return_value = [_make_session(id=1, pinned=True)]
        m["repository"].count_messages.return_value = 5

        result = await service.list_sessions()

        assert isinstance(result, list)
        item = result[0]
        assert item.id == 1
        assert item.message_count == 5
        assert item.is_pinned is True
        assert item.knowledge_base_names == ["知识库A", "知识库A"]

    async def test_missing_kb_name_falls_back(self) -> None:
        service, m = _make_service(kb_get_by_id=AsyncMock(return_value=None))
        m["repository"].list_all.return_value = [_make_session()]

        result = await service.list_sessions()

        assert result[0].knowledge_base_names == ["未知知识库", "未知知识库"]


class TestGetDetail:
    async def test_returns_detail_with_kb_list_and_typed_messages(self) -> None:
        service, m = _make_service()
        m["repository"].list_messages.return_value = [
            SimpleNamespace(id=1, role="user", content="问题", created_at=datetime(2026, 7, 20, 10, 1, 0)),
            SimpleNamespace(id=2, role="assistant", content="答案", created_at=datetime(2026, 7, 20, 10, 2, 0)),
        ]

        detail = await service.get_detail(1)

        assert detail.id == 1
        assert [kb.id for kb in detail.knowledge_bases] == [1, 1]
        assert detail.messages[0].type == "user"
        assert detail.messages[1].type == "assistant"

    async def test_not_found_raises(self) -> None:
        service, _ = _make_service(get_by_id=AsyncMock(return_value=None))
        with pytest.raises(BusinessException) as exc:
            await service.get_detail(999)
        assert exc.value.error_code is ErrorCode.RAG_SESSION_NOT_FOUND


class TestMutations:
    async def test_update_title_commits(self) -> None:
        service, m = _make_service()
        await service.update_title(1, "新标题")
        m["repository"].update_title.assert_awaited_once()
        assert m["repository"].update_title.call_args.args[2] == "新标题"
        m["session"].commit.assert_awaited()

    async def test_toggle_pin_flips_and_commits(self) -> None:
        service, m = _make_service(get_by_id=AsyncMock(return_value=_make_session(pinned=False)))
        await service.toggle_pin(1)
        assert m["repository"].update_pinned.call_args.args[2] is True
        m["session"].commit.assert_awaited()

    async def test_delete_commits(self) -> None:
        service, m = _make_service()
        await service.delete(1)
        m["repository"].delete.assert_awaited_once()
        m["session"].commit.assert_awaited()


class TestStreamQuery:
    async def test_streams_text_chunks_no_json_envelope(self) -> None:
        service, m = _make_service()
        events = [chunk async for chunk in service.stream_query(1, "什么是索引？")]

        # 短答案经 probe window 归一化后整体输出为纯文本，无 JSON 包裹/无 [DONE]
        assert any("这是" in e and "答案" in e for e in events)
        assert all("[DONE]" not in e for e in events)
        assert all('"delta"' not in e for e in events)
        m["repository"].add_message.assert_awaited()

    async def test_long_answer_passthrough_streams_incrementally(self) -> None:
        long_token = "答" * 130
        service, m = _make_service()
        m["chat"].astream = MagicMock(return_value=_astream([long_token, "尾部"]))
        events = [chunk async for chunk in service.stream_query(1, "问题")]
        assert any("尾部" in e for e in events)
        assert all("[DONE]" not in e for e in events)

    async def test_no_result_stream_emits_text(self) -> None:
        service, _ = _make_service(search=AsyncMock(return_value=[]))
        events = [chunk async for chunk in service.stream_query(1, "无关")]
        assert any("未找到" in e for e in events)
        assert all('"noResult"' not in e for e in events)

    async def test_missing_session_yields_error_event(self) -> None:
        service, _ = _make_service(get_by_id=AsyncMock(return_value=None))
        events = [chunk async for chunk in service.stream_query(999, "问题")]
        assert any(e.startswith("event: error") for e in events)


class TestStreamAiErrorClassification:
    async def test_rate_limit_yields_error_event_with_ai_message(self) -> None:
        service, m = _make_service()
        exc = openai.RateLimitError("rate", response=httpx.Response(429, request=_ERR_REQUEST), body=None)
        m["chat"].astream = MagicMock(return_value=_astream_then_raise(exc))
        events = [chunk async for chunk in service.stream_query(1, "问题")]
        assert any(e.startswith("event: error") and ErrorCode.AI_RATE_LIMIT_EXCEEDED.message in e for e in events)

    async def test_non_ai_error_yields_generic_message(self) -> None:
        service, m = _make_service()
        m["chat"].astream = MagicMock(return_value=_astream_then_raise(RuntimeError("boom")))
        events = [chunk async for chunk in service.stream_query(1, "问题")]
        assert any(e.startswith("event: error") and "RAG 流式问答失败" in e for e in events)


class TestNoInfoAnswerNormalization:
    async def test_stream_replaces_no_info_in_probe_window(self) -> None:
        service, m = _make_service()
        m["chat"].astream = MagicMock(return_value=_astream(["没有找到相关信息。"]))
        events = [chunk async for chunk in service.stream_query(1, "问题")]
        assert any("未找到" in e for e in events)
        m["repository"].add_message.assert_awaited()


class TestErrorPersistence:
    async def test_stream_persists_placeholder_on_failure(self) -> None:
        service, m = _make_service(search=AsyncMock(side_effect=RuntimeError("boom")))
        events = [chunk async for chunk in service.stream_query(1, "问题")]
        assert any(e.startswith("event: error") for e in events)
        # 用户消息 + 错误占位助手消息
        assert m["repository"].add_message.await_count >= 2
