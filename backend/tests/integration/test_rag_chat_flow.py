"""RAG 发消息流式集成竖切（ADR-0016）：真 HTTP -> 真服务 -> 真库，仅假 AI 边界。

覆盖"选知识库建会话 -> 发问题 -> 流式回答 -> 落库消息"整链，断言真库落 user + assistant 两条消息、
SSE 帧回传答案。仅替身化 AI 边界（embeddings / 向量检索 / 流式 LLM —— 均依赖真实 AI 供应商，
无法在本地真跑），其余全真：路由 / 限流 / 会话 CRUD（含 KB 存在校验）/ stream_query 与 _retrieve
编排 / 消息持久化。分层单测（api mock 服务）证明不了此链拼通，此竖切正是 ADR-0016 要补的"按钮 -> 数据"。
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import settings
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.db.models.knowledge_base import KnowledgeBase
from app.infrastructure.db.models.rag_chat import RagChatMessage
from app.infrastructure.vector.repository import SearchResult, VectorRepository

_QUESTION = "数据库连接怎么优化？"
_ANSWER_TOKENS = ["根据知识库，", "推荐使用连接池并复用连接。"]
_HIT_CONTENT = "连接池能显著降低连接握手开销。"


class _FakeToken:
    """模拟 LangChain 流式返回的 chunk：只暴露 .content。"""

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeStreamingChatClient:
    async def astream(self, messages: object) -> AsyncIterator[_FakeToken]:
        for text in _ANSWER_TOKENS:
            yield _FakeToken(text)


class _FakeEmbeddings:
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


async def _fake_get_streaming_chat_client(
    self: LlmProviderRegistry, provider_id: int | None = None
) -> _FakeStreamingChatClient:
    return _FakeStreamingChatClient()


async def _fake_get_default_embeddings(self: LlmProviderRegistry) -> _FakeEmbeddings:
    return _FakeEmbeddings()


async def _fake_vector_search(
    self: VectorRepository,
    session: object,
    query_embedding: object,
    kb_ids: list[int],
    top_k: object,
) -> list[SearchResult]:
    """固定命中：embeddings/向量检索依赖真实 AI，故其结果一并替身化（见模块 docstring）。"""
    return [SearchResult(content=_HIT_CONTENT, score=0.95, kb_id=kb_ids[0])]


def _seed_knowledge_base() -> int:
    """直接落一条 KB（向量化已 COMPLETED）供建会话校验；不经上传/向量化异步链。"""

    async def _run() -> int:
        engine = create_async_engine(settings.database_url)
        try:
            async with AsyncSession(engine) as db:
                kb = KnowledgeBase(
                    file_hash="rag-vertical-kb-hash",
                    original_filename="db-notes.txt",
                    name="数据库知识库",
                    category="Database",
                    vector_status="COMPLETED",
                )
                db.add(kb)
                await db.commit()
                await db.refresh(kb)
                return kb.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _load_messages(session_pk: int) -> list[tuple[str, str | None]]:
    async def _run() -> list[tuple[str, str | None]]:
        engine = create_async_engine(settings.database_url)
        try:
            async with AsyncSession(engine) as db:
                rows = (
                    (
                        await db.execute(
                            select(RagChatMessage)
                            .where(RagChatMessage.session_id == session_pk)
                            .order_by(RagChatMessage.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                return [(m.role, m.content) for m in rows]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_rag_send_message_streams_and_persists(
    integration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """选知识库建会话 -> 发问题 -> 流式回答；断言真库落 user+assistant 消息 + SSE 含答案。"""
    # AI 边界替身：关掉 query 改写（免真实 chat client），假化 embeddings/检索/流式 LLM
    monkeypatch.setattr(settings, "rag_query_rewrite_enabled", False)
    monkeypatch.setattr(LlmProviderRegistry, "get_default_embeddings", _fake_get_default_embeddings)
    monkeypatch.setattr(LlmProviderRegistry, "get_streaming_chat_client", _fake_get_streaming_chat_client)
    monkeypatch.setattr(VectorRepository, "search", _fake_vector_search)

    kb_id = _seed_knowledge_base()

    # 1) 建会话：真 HTTP -> 真服务（校验 KB 存在为真）-> 真库 insert
    create = integration_client.post(
        "/api/rag-chat/sessions",
        json={"knowledgeBaseIds": [kb_id], "title": "连接池咨询"},
    )
    assert create.status_code == 200
    body = create.json()
    assert body["code"] == 200
    session_pk = body["data"]["id"]
    assert body["data"]["knowledgeBaseIds"] == [kb_id]

    # 2) 发消息流式：真 stream_query -> 假检索命中 -> 假流式 LLM -> 真库落消息
    stream = integration_client.post(
        f"/api/rag-chat/sessions/{session_pk}/messages/stream",
        json={"question": _QUESTION},
    )
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert _ANSWER_TOKENS[1] in stream.text  # 假 LLM 答案 token 经 SSE 帧回传

    # 3) 竖切核心：真库落 user + assistant 两条消息（按钮 -> 数据）
    answer = "".join(_ANSWER_TOKENS)
    messages = _load_messages(session_pk)
    assert messages == [("user", _QUESTION), ("assistant", answer)]
