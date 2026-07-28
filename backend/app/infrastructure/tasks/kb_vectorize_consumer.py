import asyncio
import logging
import uuid

from langchain_openai import OpenAIEmbeddings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.services.kb_document import aggregate_vector_status
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.db.repositories.knowledge_base_document_repository import (
    KnowledgeBaseDocumentRepository,
)
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.parsing.chunker import TokenChunker
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_consumer import BaseStreamConsumer
from app.infrastructure.tasks.constants import (
    EMBEDDING_BATCH_SIZE,
    FIELD_RETRY_COUNT,
    STREAM_MAX_LEN,
    StreamConfig,
)
from app.infrastructure.tasks.kb_vectorize_producer import FIELD_DOCUMENT_ID, KbVectorizePayload
from app.infrastructure.vector.repository import VectorItem, VectorRepository

logger = logging.getLogger(__name__)


class VectorizeStreamConsumer(BaseStreamConsumer[KbVectorizePayload]):
    """知识库向量化消费者：分块 + Embedding + pgvector 两阶段提交（pending -> promoted）。

    幂等策略：should_skip 恒 False；幂等下沉到 mark_processing（COMPLETED 不转 PROCESSING）
    与 process_business（COMPLETED/已删除跳过）。向量写入采用两阶段：先 insert_pending 提交，
    再删除旧向量并 promote 提交；任一阶段失败则按 job_id 清理残留 pending。
    """

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        session_factory: async_sessionmaker[AsyncSession],
        repository: KnowledgeBaseRepository,
        vector_repository: VectorRepository,
        chunker: TokenChunker,
        llm_registry: LlmProviderRegistry,
        document_repository: KnowledgeBaseDocumentRepository | None = None,
    ) -> None:
        super().__init__(redis_client, config)
        self._session_factory = session_factory
        self._repository = repository
        self._vector_repository = vector_repository
        self._chunker = chunker
        self._llm_registry = llm_registry
        self._document_repository = document_repository or KnowledgeBaseDocumentRepository()

    def task_display_name(self) -> str:
        return "知识库向量化"

    def parse_payload(self, msg_id: str, data: dict[bytes, bytes]) -> KbVectorizePayload | None:
        raw = data.get(self._config.id_field.encode())
        if raw is None:
            logger.warning("向量化消息缺少 %s，跳过: msgId=%s", self._config.id_field, msg_id)
            return None
        try:
            kb_id = int(raw)
        except (ValueError, TypeError):
            logger.warning("向量化消息 %s 解析失败，跳过: msgId=%s", self._config.id_field, msg_id)
            return None
        raw_doc = data.get(FIELD_DOCUMENT_ID.encode())
        if raw_doc is None:
            logger.warning("向量化消息缺少 documentId，跳过: msgId=%s", msg_id)
            return None
        try:
            document_id = int(raw_doc)
        except (ValueError, TypeError):
            logger.warning("向量化消息 documentId 解析失败，跳过: msgId=%s", msg_id)
            return None
        return KbVectorizePayload(knowledge_base_id=kb_id, document_id=document_id)

    def payload_identifier(self, payload: KbVectorizePayload) -> str:
        return f"knowledgeBaseId={payload.knowledge_base_id}, documentId={payload.document_id}"

    async def mark_processing(self, payload: KbVectorizePayload) -> None:
        async with self._session_factory() as session:
            doc = await self._document_repository.get_by_id(session, payload.document_id)
            if doc is None:
                logger.warning("知识库文档已删除，跳过 mark_processing: documentId=%s", payload.document_id)
                return
            if doc.vector_status == AsyncTaskStatus.COMPLETED.value:
                logger.info("文档已向量化完成，跳过重复处理: documentId=%s", payload.document_id)
                return
            await self._document_repository.update_vector_status(session, doc, AsyncTaskStatus.PROCESSING.value, None)
            await self._sync_kb_aggregate(session, payload.knowledge_base_id)
            await session.commit()

    async def process_business(self, payload: KbVectorizePayload) -> None:
        await self._process_document(payload.knowledge_base_id, payload.document_id)

    async def _process_document(self, kb_id: int, document_id: int) -> None:
        """文档粒度向量化（ADR-0018）：两阶段提交，删除/归属按 document_id。"""
        async with self._session_factory() as session:
            doc = await self._document_repository.get_by_id(session, document_id)
            if doc is None:
                logger.warning("知识库文档已删除，跳过向量化: documentId=%s", document_id)
                return
            if doc.vector_status == AsyncTaskStatus.COMPLETED.value:
                logger.info("文档已向量化完成，跳过重复向量化: documentId=%s", document_id)
                return
            content_text = doc.content_text or ""

        chunks = await asyncio.to_thread(self._chunker.split, content_text)
        job_id = uuid.uuid4().hex

        if not chunks:
            logger.warning("文档无可向量化文本: documentId=%s", document_id)
            async with self._session_factory() as session:
                doc = await self._document_repository.get_by_id(session, document_id)
                if doc is None:
                    return
                await self._vector_repository.delete_by_document_id(session, document_id)
                await self._document_repository.mark_vectorized(session, doc, job_id, 0)
                await self._sync_kb_aggregate(session, kb_id)
                await session.commit()
            return

        embeddings = await self._llm_registry.get_default_embeddings()
        vectors = await self._embed_in_batches(embeddings, chunks)
        items = [
            VectorItem(content=chunk, embedding=vector, metadata={"chunkIndex": index})
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]

        try:
            async with self._session_factory() as session:
                await self._vector_repository.insert_pending(session, job_id, kb_id, items, document_id=document_id)
                await session.commit()

            async with self._session_factory() as session:
                doc = await self._document_repository.get_by_id(session, document_id)
                if doc is None:
                    await self._vector_repository.delete_by_vector_job_id(session, job_id)
                    await session.commit()
                    return
                await self._vector_repository.delete_by_document_id(session, document_id)
                await self._vector_repository.promote_vector_job(session, kb_id, job_id)
                await self._document_repository.mark_vectorized(session, doc, job_id, len(items))
                await self._sync_kb_aggregate(session, kb_id)
                await session.commit()
        except Exception:
            await self._cleanup_pending(job_id)
            raise

        logger.info("文档向量化完成: documentId=%s, chunks=%d", document_id, len(items))

    async def _sync_kb_aggregate(self, session: AsyncSession, kb_id: int) -> None:
        """KB 级 vector_status/chunk_count 为文档状态的聚合视图（ADR-0018）。"""
        kb = await self._repository.get_by_id(session, kb_id)
        if kb is None:
            return
        statuses = await self._document_repository.list_statuses_by_kb(session, kb_id)
        aggregated = aggregate_vector_status(statuses)
        kb.vector_status = aggregated
        kb.vector_error = "存在向量化失败的文档" if aggregated == AsyncTaskStatus.FAILED.value else None
        kb.chunk_count = await self._document_repository.sum_chunk_count_by_kb(session, kb_id)
        await session.flush()

    async def mark_completed(self, payload: KbVectorizePayload) -> None:
        async with self._session_factory() as session:
            doc = await self._document_repository.get_by_id(session, payload.document_id)
            if doc is None:
                return
            await self._document_repository.update_vector_status(session, doc, AsyncTaskStatus.COMPLETED.value)
            await self._sync_kb_aggregate(session, payload.knowledge_base_id)
            await session.commit()

    async def mark_failed(self, payload: KbVectorizePayload, error: str) -> None:
        async with self._session_factory() as session:
            doc = await self._document_repository.get_by_id(session, payload.document_id)
            if doc is None:
                return
            await self._document_repository.update_vector_status(session, doc, AsyncTaskStatus.FAILED.value, error)
            await self._sync_kb_aggregate(session, payload.knowledge_base_id)
            await session.commit()

    async def retry_message(self, payload: KbVectorizePayload, retry_count: int) -> None:
        message = {
            self._config.id_field: str(payload.knowledge_base_id),
            FIELD_RETRY_COUNT: str(retry_count),
            FIELD_DOCUMENT_ID: str(payload.document_id),
        }
        await self._redis.xadd(self._config.stream_key, message, max_len=STREAM_MAX_LEN)
        logger.info(
            "知识库向量化任务已重新入队: knowledgeBaseId=%s, documentId=%s, retryCount=%s",
            payload.knowledge_base_id,
            payload.document_id,
            retry_count,
        )

    async def _embed_in_batches(self, embeddings: OpenAIEmbeddings, chunks: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
            batch = chunks[start : start + EMBEDDING_BATCH_SIZE]
            batch_vectors = await embeddings.aembed_documents(batch)
            vectors.extend(batch_vectors)
        return vectors

    async def _cleanup_pending(self, job_id: str) -> None:
        try:
            async with self._session_factory() as session:
                await self._vector_repository.delete_by_vector_job_id(session, job_id)
                await session.commit()
        except Exception as e:
            logger.error("清理残留 pending 向量失败: jobId=%s, error=%s", job_id, e)
