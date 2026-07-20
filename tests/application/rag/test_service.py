import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.rag.service import RagChatService, RagConfig
from app.domain.errors import BusinessException, ErrorCode
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


def _make_factory() -> MagicMock:
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


async def _astream(tokens: list[str]) -> Any:
    for token in tokens:
        yield SimpleNamespace(content=token)


def _make_service(**over: Any) -> tuple[RagChatService, dict[str, Any]]:
    session = over.get("session") or AsyncMock()
    repository = MagicMock()
    repository.get_by_session_id = over.get("get_by_session_id") or AsyncMock(return_value=_make_session())
    repository.get_by_id = AsyncMock()
    repository.list_paginated = AsyncMock(return_value=([], 0))
    repository.list_messages = AsyncMock(return_value=[])
    repository.recent_history = AsyncMock(return_value=[])
    repository.add_message = AsyncMock()
    repository.delete = AsyncMock()
    repository.update_pinned = AsyncMock()

    async def _save(_s: Any, entity: RagChatSession) -> RagChatSession:
        entity.id = 1
        entity.created_at = datetime(2026, 7, 20, 10, 0, 0)
        entity.updated_at = datetime(2026, 7, 20, 10, 0, 0)
        return entity

    repository.save = AsyncMock(side_effect=_save)

    kb_repository = MagicMock()
    kb_repository.get_by_id = over.get("kb_get_by_id") or AsyncMock(return_value=object())

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
        assert dto.knowledge_base_ids == [1, 2]
        assert dto.status == "ACTIVE"
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


class TestSessionLookups:
    async def test_get_detail_not_found_raises(self) -> None:
        service, _ = _make_service(get_by_session_id=AsyncMock(return_value=None))
        with pytest.raises(BusinessException) as exc:
            await service.get_detail("missing")
        assert exc.value.error_code is ErrorCode.RAG_SESSION_NOT_FOUND

    async def test_toggle_pin_flips(self) -> None:
        service, m = _make_service(get_by_session_id=AsyncMock(return_value=_make_session(pinned=False)))
        await service.toggle_pin("sess-abc")
        assert m["repository"].update_pinned.call_args.args[2] is True

    async def test_delete_commits(self) -> None:
        service, m = _make_service()
        await service.delete("sess-abc")
        m["repository"].delete.assert_awaited_once()
        m["session"].commit.assert_awaited()


class TestQuery:
    async def test_happy_path_persists_and_answers(self) -> None:
        service, m = _make_service()
        result = await service.query("sess-abc", "什么是索引？")
        assert result.no_result is False
        assert result.answer == "这是基于知识库的答案"
        assert result.sources[0].content == "片段A"
        # 用户消息 + 助手消息
        assert m["repository"].add_message.await_count == 2

    async def test_no_result_returns_fixed_message(self) -> None:
        service, m = _make_service(search=AsyncMock(return_value=[]))
        result = await service.query("sess-abc", "无关问题")
        assert result.no_result is True
        assert "未找到" in result.answer
        m["chat"].ainvoke.assert_not_awaited()

    async def test_below_min_score_is_no_result(self) -> None:
        service, _ = _make_service(search=AsyncMock(return_value=[SearchResult("弱相关", 0.1, 1)]))
        result = await service.query("sess-abc", "问题")
        assert result.no_result is True


class TestStreamQuery:
    async def test_streams_tokens_and_done(self) -> None:
        service, m = _make_service()
        events = [chunk async for chunk in service.stream_query("sess-abc", "什么是索引？")]

        # 短答案经 probe window 归一化后整体输出
        assert any("这是" in e and "答案" in e for e in events)
        assert events[-1] == "data: [DONE]\n\n"
        # 助手消息经 factory 持久化
        m["repository"].add_message.assert_awaited()

    async def test_long_answer_passthrough_streams_incrementally(self) -> None:
        # 超过 probe_window(120) 后切换 passthrough，逐 token 输出
        long_token = "答" * 130
        service, m = _make_service()
        m["chat"].astream = MagicMock(return_value=_astream([long_token, "尾部"]))
        events = [chunk async for chunk in service.stream_query("sess-abc", "问题")]
        # 首 130 字符作为一次 delta 输出，随后 "尾部" 单独输出
        assert events[-1] == "data: [DONE]\n\n"
        assert m["repository"].add_message.await_count >= 2

    async def test_no_result_stream(self) -> None:
        service, _ = _make_service(search=AsyncMock(return_value=[]))
        events = [chunk async for chunk in service.stream_query("sess-abc", "无关")]
        assert any("未找到" in e for e in events)
        assert events[-1] == "data: [DONE]\n\n"

    async def test_missing_session_yields_error_event(self) -> None:
        service, _ = _make_service(get_by_session_id=AsyncMock(return_value=None))
        events = [chunk async for chunk in service.stream_query("missing", "问题")]
        assert any('"error"' in e for e in events)
        assert events[-1] == "data: [DONE]\n\n"


class TestNoInfoAnswerNormalization:
    async def test_query_replaces_no_info_answer(self) -> None:
        # LLM 返回无信息模板 -> 替换为标准提示，no_result=True
        service, m = _make_service()
        m["chat"].ainvoke = AsyncMock(return_value=SimpleNamespace(content="没有找到相关信息。"))
        result = await service.query("sess-abc", "问题")
        assert result.no_result is True
        assert "未找到" in result.answer
        assert m["repository"].add_message.await_count == 2

    async def test_stream_replaces_no_info_in_probe_window(self) -> None:
        # 流式前 120 字符命中无信息模板 -> 输出固定提示并结束
        service, m = _make_service()
        m["chat"].astream = MagicMock(return_value=_astream(["没有找到相关信息。"]))
        events = [chunk async for chunk in service.stream_query("sess-abc", "问题")]
        assert any("未找到" in e for e in events)
        assert any('"noResult": true' in e or '"noResult":True' in e for e in events)
        assert events[-1] == "data: [DONE]\n\n"
        m["repository"].add_message.assert_awaited()


class TestErrorPersistence:
    async def test_query_persists_placeholder_on_failure(self) -> None:
        # _retrieve 抛异常 -> 持久化错误占位助手消息 + 重抛
        service, m = _make_service(search=AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            await service.query("sess-abc", "问题")
        # 用户消息 + 错误占位助手消息
        assert m["repository"].add_message.await_count == 2
        last_call = m["repository"].add_message.await_args
        assistant_msg = last_call.args[1]
        assert assistant_msg.role == "assistant"
        assert "失败" in (assistant_msg.content or "")

    async def test_stream_persists_placeholder_on_failure(self) -> None:
        service, m = _make_service(search=AsyncMock(side_effect=RuntimeError("boom")))
        events = [chunk async for chunk in service.stream_query("sess-abc", "问题")]
        assert any('"error"' in e for e in events)
        assert events[-1] == "data: [DONE]\n\n"
        # 用户消息 + 错误占位助手消息
        assert m["repository"].add_message.await_count >= 2
