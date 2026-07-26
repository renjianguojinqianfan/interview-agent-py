from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.knowledge_base import KnowledgeBaseDocument


class KnowledgeBaseDocumentRepository:
    """知识库文档异步仓储（ADR-0018）。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def save(self, session: AsyncSession, doc: KnowledgeBaseDocument) -> KnowledgeBaseDocument:
        session.add(doc)
        await session.flush()
        return doc

    async def get_by_id(self, session: AsyncSession, document_id: int) -> KnowledgeBaseDocument | None:
        result = await session.execute(select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.id == document_id))
        return result.scalar_one_or_none()

    async def find_by_kb_and_hash(
        self, session: AsyncSession, kb_id: int, file_hash: str
    ) -> KnowledgeBaseDocument | None:
        result = await session.execute(
            select(KnowledgeBaseDocument).where(
                KnowledgeBaseDocument.knowledge_base_id == kb_id,
                KnowledgeBaseDocument.file_hash == file_hash,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_kb(self, session: AsyncSession, kb_id: int) -> list[KnowledgeBaseDocument]:
        result = await session.execute(
            select(KnowledgeBaseDocument)
            .where(KnowledgeBaseDocument.knowledge_base_id == kb_id)
            .order_by(KnowledgeBaseDocument.uploaded_at.asc(), KnowledgeBaseDocument.id.asc())
        )
        return list(result.scalars().all())

    async def list_statuses_by_kb(self, session: AsyncSession, kb_id: int) -> list[str]:
        result = await session.execute(
            select(KnowledgeBaseDocument.vector_status).where(KnowledgeBaseDocument.knowledge_base_id == kb_id)
        )
        return list(result.scalars().all())

    async def sum_chunk_count_by_kb(self, session: AsyncSession, kb_id: int) -> int:
        docs = await self.list_by_kb(session, kb_id)
        return sum(doc.chunk_count for doc in docs)

    async def delete(self, session: AsyncSession, doc: KnowledgeBaseDocument) -> None:
        await session.delete(doc)

    async def update_vector_status(
        self, session: AsyncSession, doc: KnowledgeBaseDocument, status: str, error: str | None = None
    ) -> None:
        doc.vector_status = status
        doc.vector_error = error
        await session.flush()

    async def mark_vectorized(
        self, session: AsyncSession, doc: KnowledgeBaseDocument, job_id: str, chunk_count: int
    ) -> None:
        doc.vector_job_id = job_id
        doc.chunk_count = chunk_count
        doc.vectorized_at = datetime.now(UTC)
        await session.flush()
