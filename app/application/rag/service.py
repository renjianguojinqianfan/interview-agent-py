"""RAG 聊天应用服务：会话 CRUD + 非流式/流式问答编排。

并发安全约束：AsyncSession 非线程/协程安全，因此 asyncio.gather 多候选检索的每个分支
各自从 session_factory 开短事务；流式问答全程用 session_factory（请求 session 在流式期间可能已关闭）。
检索前后的纯策略委托 domain/services/rag_query。
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.rag.schemas import (
    RagAnswerDTO,
    RagMessageDTO,
    RagSessionDetailDTO,
    RagSessionInfoDTO,
    RagSessionPageDTO,
    RagSourceDTO,
)
from app.domain.entities.rag_session import RagSessionStatus
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.rag_query import (
    RetrievedChunk,
    build_context,
    compute_top_k,
    detect_no_result,
    filter_by_min_score,
    merge_and_dedup,
    normalize_probe_window,
)
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.prompt_loader import load_prompt
from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer
from app.infrastructure.db.models.rag_chat import RagChatMessage, RagChatSession
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.db.repositories.rag_chat_repository import RagChatRepository
from app.infrastructure.vector.repository import VectorRepository

logger = logging.getLogger(__name__)

_USER_ROLE = "user"
_ASSISTANT_ROLE = "assistant"
_DONE = "data: [DONE]\n\n"
_NO_RESULT_MESSAGE = "抱歉，知识库中未找到与您问题相关的信息。请尝试换一种问法，或确认已选择正确的知识库。"


@dataclass(frozen=True)
class RagConfig:
    default_top_k: int
    min_score: float
    probe_window: int
    query_rewrite_enabled: bool
    max_context_chars: int
    history_limit: int


def _sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _content_to_str(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return str(content)


class RagChatService:
    def __init__(
        self,
        session: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession],
        repository: RagChatRepository,
        kb_repository: KnowledgeBaseRepository,
        vector_repository: VectorRepository,
        llm_registry: LlmProviderRegistry,
        config: RagConfig,
        sanitizer: PromptSanitizer | None = None,
    ) -> None:
        self._session = session
        self._session_factory = session_factory
        self._repository = repository
        self._kb_repository = kb_repository
        self._vector_repository = vector_repository
        self._llm_registry = llm_registry
        self._config = config
        self._sanitizer = sanitizer or PromptSanitizer()

    # ---------------- 会话 CRUD ----------------

    async def create_session(self, kb_ids: list[int], title: str | None) -> RagSessionInfoDTO:
        if not kb_ids:
            raise BusinessException(ErrorCode.BAD_REQUEST, "请至少选择一个知识库")
        for kb_id in kb_ids:
            kb = await self._kb_repository.get_by_id(self._session, kb_id)
            if kb is None:
                raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND, f"知识库不存在: {kb_id}")

        entity = RagChatSession(
            session_id=uuid.uuid4().hex,
            knowledge_base_ids_json=json.dumps(kb_ids),
            title=title,
            status=RagSessionStatus.ACTIVE.value,
            pinned=False,
        )
        await self._repository.save(self._session, entity)
        await self._session.commit()
        logger.info("RAG 会话已创建: sessionId=%s, kbIds=%s", entity.session_id, kb_ids)
        return self._to_info(entity)

    async def list_sessions(self, page: int, size: int) -> RagSessionPageDTO:
        sessions, total = await self._repository.list_paginated(self._session, page, size)
        return RagSessionPageDTO(
            items=[self._to_info(s) for s in sessions],
            total=total,
            page=page,
            size=size,
        )

    async def get_detail(self, session_id: str) -> RagSessionDetailDTO:
        sess = await self._get_or_raise(self._session, session_id)
        messages = await self._repository.list_messages(self._session, sess.id)
        return RagSessionDetailDTO(
            id=sess.id,
            session_id=sess.session_id,
            title=sess.title,
            status=sess.status,
            pinned=sess.pinned,
            knowledge_base_ids=self._kb_ids(sess),
            created_at=sess.created_at,
            updated_at=sess.updated_at,
            messages=[self._to_message_dto(m) for m in messages],
        )

    async def delete(self, session_id: str) -> None:
        sess = await self._get_or_raise(self._session, session_id)
        await self._repository.delete(self._session, sess)
        await self._session.commit()
        logger.info("RAG 会话已删除: sessionId=%s", session_id)

    async def toggle_pin(self, session_id: str) -> bool:
        sess = await self._get_or_raise(self._session, session_id)
        await self._repository.update_pinned(self._session, sess, not sess.pinned)
        await self._session.commit()
        return sess.pinned

    async def get_messages(self, session_id: str) -> list[RagMessageDTO]:
        sess = await self._get_or_raise(self._session, session_id)
        messages = await self._repository.list_messages(self._session, sess.id)
        return [self._to_message_dto(m) for m in messages]

    async def ensure_session_exists(self, session_id: str) -> None:
        await self._get_or_raise(self._session, session_id)

    # ---------------- 非流式问答 ----------------

    async def query(self, session_id: str, question: str) -> RagAnswerDTO:
        sess = await self._get_or_raise(self._session, session_id)
        kb_ids = self._kb_ids(sess)
        history = await self._repository.recent_history(self._session, sess.id, self._config.history_limit)
        history_text = self._format_history(history)
        await self._repository.add_message(
            self._session, RagChatMessage(session_id=sess.id, role=_USER_ROLE, content=question)
        )
        await self._session.commit()

        chunks, sources = await self._retrieve(question, kb_ids, history_text)
        no_result = detect_no_result(chunks)
        if no_result:
            answer = _NO_RESULT_MESSAGE
        else:
            answer = await self._answer(question, build_context(chunks, self._config.max_context_chars))

        await self._repository.add_message(self._session, self._assistant_message(sess.id, answer, sources))
        await self._session.commit()
        return RagAnswerDTO(answer=answer, sources=sources, no_result=no_result)

    # ---------------- 流式问答（SSE） ----------------

    async def stream_query(self, session_id: str, question: str) -> AsyncIterator[str]:
        try:
            async with self._session_factory() as s:
                sess = await self._get_or_raise(s, session_id)
                session_pk = sess.id
                kb_ids = self._kb_ids(sess)
                history_text = self._format_history(
                    await self._repository.recent_history(s, session_pk, self._config.history_limit)
                )
                await self._repository.add_message(
                    s, RagChatMessage(session_id=session_pk, role=_USER_ROLE, content=question)
                )
                await s.commit()

            chunks, sources = await self._retrieve(question, kb_ids, history_text)
            if detect_no_result(chunks):
                yield _sse({"delta": _NO_RESULT_MESSAGE})
                await self._persist_assistant_factory(session_pk, _NO_RESULT_MESSAGE, sources)
                yield _sse({"sources": [], "noResult": True})
                yield _DONE
                return

            messages = await self._answer_messages(question, build_context(chunks, self._config.max_context_chars))
            llm = await self._llm_registry.get_streaming_chat_client()
            parts: list[str] = []
            async for chunk in llm.astream(messages):
                token = _content_to_str(chunk.content)
                if token:
                    parts.append(token)
                    yield _sse({"delta": token})

            answer = "".join(parts)
            await self._persist_assistant_factory(session_pk, answer, sources)
            yield _sse({"sources": [s.model_dump() for s in sources], "noResult": False})
            yield _DONE
        except BusinessException as e:
            yield _sse({"error": e.message, "code": e.error_code.code})
            yield _DONE
        except Exception as e:
            logger.error("RAG 流式问答失败: sessionId=%s, error=%s", session_id, e)
            yield _sse({"error": "RAG 流式问答失败"})
            yield _DONE

    # ---------------- 检索与回答 ----------------

    async def _retrieve(
        self, question: str, kb_ids: list[int], history_text: str
    ) -> tuple[list[RetrievedChunk], list[RagSourceDTO]]:
        probes = await self._build_probes(question, history_text)
        embeddings = await self._llm_registry.get_default_embeddings()
        vectors = await embeddings.aembed_documents(probes)

        async def _search_one(probe: str, vector: list[float]) -> list[RetrievedChunk]:
            async with self._session_factory() as s:
                results = await self._vector_repository.search(
                    s, vector, kb_ids, compute_top_k(probe, self._config.default_top_k)
                )
            return [RetrievedChunk(content=r.content, score=r.score, kb_id=r.kb_id) for r in results]

        candidate_lists = await asyncio.gather(
            *[_search_one(probe, vector) for probe, vector in zip(probes, vectors, strict=True)]
        )
        merged = merge_and_dedup(list(candidate_lists))
        filtered = filter_by_min_score(merged, self._config.min_score)
        sources = [RagSourceDTO(content=c.content, score=c.score, kb_id=c.kb_id) for c in filtered]
        return filtered, sources

    async def _build_probes(self, question: str, history_text: str) -> list[str]:
        base = normalize_probe_window(question, self._config.probe_window)
        probes = [base] if base else [normalize_probe_window(question or "查询", self._config.probe_window)]
        if self._config.query_rewrite_enabled:
            rewritten = normalize_probe_window(await self._rewrite(question, history_text), self._config.probe_window)
            if rewritten and rewritten not in probes:
                probes.append(rewritten)
        return probes

    async def _rewrite(self, question: str, history_text: str) -> str:
        try:
            tpl = await load_prompt("knowledgebase-query-rewrite")
            sanitized = self._sanitizer.sanitize(question) or ""
            prompt = tpl.format(
                question=self._sanitizer.wrap_with_delimiters("问答内容", sanitized),
                history=history_text,
            )
            llm = await self._llm_registry.get_chat_client()
            resp = await llm.ainvoke([HumanMessage(content=prompt)])
            text = _content_to_str(resp.content).strip()
            return text or question
        except Exception as e:
            logger.warning("Query 改写失败，使用原问题: %s", e)
            return question

    async def _answer(self, question: str, context: str) -> str:
        messages = await self._answer_messages(question, context)
        llm = await self._llm_registry.get_chat_client()
        resp = await llm.ainvoke(messages)
        return _content_to_str(resp.content).strip()

    async def _answer_messages(self, question: str, context: str) -> list[BaseMessage]:
        system_tpl = await load_prompt("knowledgebase-query-system")
        user_tpl = await load_prompt("knowledgebase-query-user")
        sanitized_ctx = self._sanitizer.sanitize(context) or ""
        sanitized_q = self._sanitizer.sanitize(question) or ""
        return [
            SystemMessage(content=system_tpl.format()),
            HumanMessage(content=user_tpl.format(context=sanitized_ctx, question=sanitized_q)),
        ]

    # ---------------- 持久化与转换 ----------------

    async def _persist_assistant_factory(self, session_pk: int, answer: str, sources: list[RagSourceDTO]) -> None:
        async with self._session_factory() as s:
            await self._repository.add_message(s, self._assistant_message(session_pk, answer, sources))
            await s.commit()

    def _assistant_message(self, session_pk: int, answer: str, sources: list[RagSourceDTO]) -> RagChatMessage:
        return RagChatMessage(
            session_id=session_pk,
            role=_ASSISTANT_ROLE,
            content=answer,
            sources_json=json.dumps([s.model_dump() for s in sources], ensure_ascii=False),
        )

    async def _get_or_raise(self, session: AsyncSession, session_id: str) -> RagChatSession:
        sess = await self._repository.get_by_session_id(session, session_id)
        if sess is None:
            raise BusinessException(ErrorCode.RAG_SESSION_NOT_FOUND)
        return sess

    def _kb_ids(self, sess: RagChatSession) -> list[int]:
        return [int(x) for x in json.loads(sess.knowledge_base_ids_json)]

    def _format_history(self, messages: list[RagChatMessage]) -> str:
        if not messages:
            return ""
        lines = [f"{'用户' if m.role == _USER_ROLE else '助手'}: {m.content or ''}" for m in messages]
        return "对话历史：\n" + "\n".join(lines)

    def _to_info(self, sess: RagChatSession) -> RagSessionInfoDTO:
        return RagSessionInfoDTO(
            id=sess.id,
            session_id=sess.session_id,
            title=sess.title,
            status=sess.status,
            pinned=sess.pinned,
            knowledge_base_ids=self._kb_ids(sess),
            created_at=sess.created_at,
            updated_at=sess.updated_at,
        )

    def _to_message_dto(self, message: RagChatMessage) -> RagMessageDTO:
        sources: list[RagSourceDTO] = []
        if message.sources_json:
            sources = [RagSourceDTO(**item) for item in json.loads(message.sources_json)]
        return RagMessageDTO(
            id=message.id,
            role=message.role,
            content=message.content,
            sources=sources,
            created_at=message.created_at,
        )
