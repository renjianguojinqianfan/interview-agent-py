from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.knowledge_base import KnowledgeBaseDocument


@dataclass(frozen=True)
class DocAggregate:
    """按 KB 聚合的文档统计（批量查询用，避免 N+1）。"""

    file_size_sum: int
    first_original_filename: str | None
    first_content_type: str | None


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
        result = await session.execute(
            select(func.coalesce(func.sum(KnowledgeBaseDocument.chunk_count), 0)).where(
                KnowledgeBaseDocument.knowledge_base_id == kb_id
            )
        )
        return result.scalar_one()

    async def find_first_hash_by_kb(self, session: AsyncSession, kb_id: int) -> str | None:
        """获取知识库首文档的 file_hash（按上传时间排序）。"""
        result = await session.execute(
            select(KnowledgeBaseDocument.file_hash)
            .where(KnowledgeBaseDocument.knowledge_base_id == kb_id)
            .order_by(KnowledgeBaseDocument.uploaded_at.asc(), KnowledgeBaseDocument.id.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

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

    async def aggregate_by_kb_ids(self, session: AsyncSession, kb_ids: list[int]) -> dict[int, DocAggregate]:
        """批量查询多个 KB 的文档聚合信息（file_size 求和 + 首文档的 filename/content_type）。

        首文档按 uploaded_at ASC, id ASC 排序取第一条，与 find_first_hash_by_kb 语义一致。
        """
        if not kb_ids:
            return {}

        # 1. file_size 聚合
        sum_result = await session.execute(
            select(
                KnowledgeBaseDocument.knowledge_base_id,
                func.coalesce(func.sum(func.coalesce(KnowledgeBaseDocument.file_size, 0)), 0).label("file_size_sum"),
            )
            .where(KnowledgeBaseDocument.knowledge_base_id.in_(kb_ids))
            .group_by(KnowledgeBaseDocument.knowledge_base_id)
        )
        sum_rows = {r.knowledge_base_id: r.file_size_sum for r in sum_result}
        if not sum_rows:
            return {}

        # 2. 首文档：ROW_NUMBER() OVER (PARTITION BY kb_id ORDER BY uploaded_at, id)
        row_num = (
            func.row_number()
            .over(
                partition_by=KnowledgeBaseDocument.knowledge_base_id,
                order_by=(KnowledgeBaseDocument.uploaded_at.asc(), KnowledgeBaseDocument.id.asc()),
            )
            .label("rn")
        )
        first_doc_query = (
            select(
                KnowledgeBaseDocument.knowledge_base_id,
                KnowledgeBaseDocument.original_filename,
                KnowledgeBaseDocument.content_type,
                row_num,
            )
            .where(KnowledgeBaseDocument.knowledge_base_id.in_(kb_ids))
            .cte("first_doc_cte")
        )
        first_doc_result = await session.execute(select(first_doc_query).where(literal_column("rn") == 1))
        first_doc_map: dict[int, tuple[str | None, str | None]] = {
            row.knowledge_base_id: (row.original_filename, row.content_type) for row in first_doc_result
        }

        return {
            kb_id: DocAggregate(
                file_size_sum=file_size_sum,
                first_original_filename=first_doc_map.get(kb_id, (None, None))[0],
                first_content_type=first_doc_map.get(kb_id, (None, None))[1],
            )
            for kb_id, file_size_sum in sum_rows.items()
        }
