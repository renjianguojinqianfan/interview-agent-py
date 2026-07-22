"""RAG 问答应用服务：会话 CRUD + 非流式/流式问答编排。

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

from app.application.knowledgebase.service import to_kb_list_item
from app.application.rag.schemas import (
    RagMessageDTO,
    RagSessionDetailDTO,
    RagSessionDTO,
    RagSessionListItemDTO,
    RagSourceDTO,
)
from app.domain.entities.rag_session import RagSessionStatus
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.rag_query import (
    RetrievedChunk,
    build_context,
    compute_retrieval_params,
    detect_no_result,
    filter_by_min_score,
    is_no_info_answer,
    merge_and_dedup,
    normalize_probe_window,
)
from app.infrastructure.ai.ai_error import classify_ai_error
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
_NO_RESULT_MESSAGE = "抱歉，知识库中未找到与您问题相关的信息。请尝试换一种问法，或确认已选择正确的知识库。"
_ERROR_PLACEHOLDER = "[回答生成失败，请稍后重试]"


@dataclass(frozen=True)
class RagConfig:
    min_score: float
    probe_window: int
    query_rewrite_enabled: bool
    max_context_chars: int
    history_limit: int


def _escape_newlines(text: str) -> str:
    return text.replace("\n", "\\n").replace("\r", "\\r")


def _sse_text(text: str) -> str:
    """纯文本 SSE 数据帧（对齐 Java RagChatController：data 为转义换行的原始文本，前端直接拼接）。"""
    return f"data: {_escape_newlines(text)}\n\n"


def _sse_error(message: str) -> str:
    """错误 SSE 事件：前端 stream 解析器遇 event: error 抛出并进入 onError。"""
    return f"event: error\ndata: {_escape_newlines(message)}\n\n"


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

    async def create_session(self, kb_ids: list[int], title: str | None) -> RagSessionDTO:
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
        logger.info("RAG 会话已创建: id=%s, kbIds=%s", entity.id, kb_ids)
        return self._to_session_dto(entity)

    async def list_sessions(self) -> list[RagSessionListItemDTO]:
        sessions = await self._repository.list_all(self._session)
        return [await self._to_list_item(s) for s in sessions]

    async def get_detail(self, session_pk: int) -> RagSessionDetailDTO:
        sess = await self._get_or_raise(self._session, session_pk)
        messages = await self._repository.list_messages(self._session, sess.id)
        knowledge_bases = []
        for kb_id in self._kb_ids(sess):
            kb = await self._kb_repository.get_by_id(self._session, kb_id)
            if kb is not None:
                knowledge_bases.append(to_kb_list_item(kb))
        return RagSessionDetailDTO(
            id=sess.id,
            title=sess.title,
            knowledge_bases=knowledge_bases,
            messages=[self._to_message_dto(m) for m in messages],
            created_at=sess.created_at,
            updated_at=sess.updated_at,
        )

    async def update_title(self, session_pk: int, title: str) -> None:
        sess = await self._get_or_raise(self._session, session_pk)
        await self._repository.update_title(self._session, sess, title)
        await self._session.commit()
        logger.info("RAG 会话标题已更新: id=%s", session_pk)

    async def toggle_pin(self, session_pk: int) -> None:
        sess = await self._get_or_raise(self._session, session_pk)
        await self._repository.update_pinned(self._session, sess, not sess.pinned)
        await self._session.commit()

    async def delete(self, session_pk: int) -> None:
        sess = await self._get_or_raise(self._session, session_pk)
        await self._repository.delete(self._session, sess)
        await self._session.commit()
        logger.info("RAG 会话已删除: id=%s", session_pk)

    # ---------------- 流式问答（SSE） ----------------

    async def stream_query(self, session_pk: int, question: str) -> AsyncIterator[str]:
        pk: int | None = None
        try:
            async with self._session_factory() as s:
                sess = await self._get_or_raise(s, session_pk)
                pk = sess.id
                kb_ids = self._kb_ids(sess)
                history_text = self._format_history(
                    await self._repository.recent_history(s, sess.id, self._config.history_limit)
                )
                await self._repository.add_message(
                    s, RagChatMessage(session_id=sess.id, role=_USER_ROLE, content=question)
                )
                await s.commit()

            assert pk is not None  # 块内已赋值，窄化供 happy path 使用
            chunks, sources = await self._retrieve(question, kb_ids, history_text)
            if detect_no_result(chunks):
                await self._persist_assistant_factory(pk, _NO_RESULT_MESSAGE, sources)
                yield _sse_text(_NO_RESULT_MESSAGE)
                return

            messages = await self._answer_messages(question, build_context(chunks, self._config.max_context_chars))
            llm = await self._llm_registry.get_streaming_chat_client()
            # spec 挑战 4：探测窗口归一化--前 probe_window 字符增量检测无信息模板
            probe_buffer: list[str] = []
            passthrough = False
            answer_parts: list[str] = []
            async for chunk in llm.astream(messages):
                token = _content_to_str(chunk.content)
                if not token:
                    continue
                if passthrough:
                    answer_parts.append(token)
                    yield _sse_text(token)
                    continue
                probe_buffer.append(token)
                probe_text = "".join(probe_buffer)
                if is_no_info_answer(probe_text):
                    await self._persist_assistant_factory(pk, _NO_RESULT_MESSAGE, [])
                    yield _sse_text(_NO_RESULT_MESSAGE)
                    return
                if len(probe_text) >= self._config.probe_window:
                    passthrough = True
                    answer_parts.append(probe_text)
                    yield _sse_text(probe_text)
                    probe_buffer.clear()

            # 流结束：未达 probe_window 的残余缓冲做最终归一化
            if not passthrough:
                remaining = "".join(probe_buffer)
                if is_no_info_answer(remaining):
                    await self._persist_assistant_factory(pk, _NO_RESULT_MESSAGE, [])
                    yield _sse_text(_NO_RESULT_MESSAGE)
                    return
                answer_parts.append(remaining)
                yield _sse_text(remaining)

            answer = "".join(answer_parts)
            await self._persist_assistant_factory(pk, answer, sources)
        except BusinessException as e:
            await self._safe_persist_error(pk, _ERROR_PLACEHOLDER)
            yield _sse_error(e.message)
        except Exception as e:
            logger.error("RAG 流式问答失败: id=%s, error=%s", session_pk, e)
            await self._safe_persist_error(pk, _ERROR_PLACEHOLDER)
            ai_code = classify_ai_error(e)
            yield _sse_error(ai_code.message if ai_code is not None else "RAG 流式问答失败")

    # ---------------- 检索与回答 ----------------

    async def _retrieve(
        self, question: str, kb_ids: list[int], history_text: str
    ) -> tuple[list[RetrievedChunk], list[RagSourceDTO]]:
        probes = await self._build_probes(question, history_text)
        # spec 挑战 4：检索参数按原始问题长度分档（topK 硬数值 + 短查询放宽 minScore）
        top_k, tier_min_score = compute_retrieval_params(question)
        min_score = tier_min_score if tier_min_score is not None else self._config.min_score
        embeddings = await self._llm_registry.get_default_embeddings()
        vectors = await embeddings.aembed_documents(probes)

        async def _search_one(probe: str, vector: list[float]) -> list[RetrievedChunk]:
            async with self._session_factory() as s:
                results = await self._vector_repository.search(s, vector, kb_ids, top_k)
            return [RetrievedChunk(content=r.content, score=r.score, kb_id=r.kb_id) for r in results]

        candidate_lists = await asyncio.gather(
            *[_search_one(probe, vector) for probe, vector in zip(probes, vectors, strict=True)]
        )
        merged = merge_and_dedup(list(candidate_lists))
        filtered = filter_by_min_score(merged, min_score)
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

    async def _safe_persist_error(self, session_pk: int | None, placeholder: str) -> None:
        """异常分支持久化错误占位消息；自身失败仅记日志，不掩盖原异常。"""
        if session_pk is None:
            return
        try:
            await self._persist_assistant_factory(session_pk, placeholder, [])
        except Exception:
            logger.exception("持久化 RAG 错误占位消息失败: sessionPk=%s", session_pk)

    def _assistant_message(self, session_pk: int, answer: str, sources: list[RagSourceDTO]) -> RagChatMessage:
        return RagChatMessage(
            session_id=session_pk,
            role=_ASSISTANT_ROLE,
            content=answer,
            sources_json=json.dumps([s.model_dump() for s in sources], ensure_ascii=False),
        )

    async def _get_or_raise(self, session: AsyncSession, session_pk: int) -> RagChatSession:
        sess = await self._repository.get_by_id(session, session_pk)
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

    def _to_session_dto(self, sess: RagChatSession) -> RagSessionDTO:
        return RagSessionDTO(
            id=sess.id,
            title=sess.title,
            knowledge_base_ids=self._kb_ids(sess),
            created_at=sess.created_at,
        )

    async def _to_list_item(self, sess: RagChatSession) -> RagSessionListItemDTO:
        message_count = await self._repository.count_messages(self._session, sess.id)
        kb_names: list[str] = []
        for kb_id in self._kb_ids(sess):
            kb = await self._kb_repository.get_by_id(self._session, kb_id)
            kb_names.append((kb.name or kb.original_filename) if kb is not None else "未知知识库")
        return RagSessionListItemDTO(
            id=sess.id,
            title=sess.title,
            message_count=message_count,
            knowledge_base_names=kb_names,
            updated_at=sess.updated_at,
            is_pinned=sess.pinned,
        )

    def _to_message_dto(self, message: RagChatMessage) -> RagMessageDTO:
        return RagMessageDTO(
            id=message.id,
            type=message.role,
            content=message.content,
            created_at=message.created_at,
        )
