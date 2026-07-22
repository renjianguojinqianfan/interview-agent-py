from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.knowledge_base import KnowledgeBase


class KnowledgeBaseRepository:
    """知识库异步仓储。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def find_by_hash(self, session: AsyncSession, file_hash: str) -> KnowledgeBase | None:
        result = await session.execute(select(KnowledgeBase).where(KnowledgeBase.file_hash == file_hash))
        return result.scalar_one_or_none()

    async def get_by_id(self, session: AsyncSession, kb_id: int) -> KnowledgeBase | None:
        result = await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
        return result.scalar_one_or_none()

    async def save(self, session: AsyncSession, kb: KnowledgeBase) -> KnowledgeBase:
        session.add(kb)
        await session.flush()
        return kb

    async def list_all(self, session: AsyncSession, vector_status: str | None = None) -> list[KnowledgeBase]:
        query = select(KnowledgeBase)
        if vector_status is not None:
            query = query.where(KnowledgeBase.vector_status == vector_status)
        query = query.order_by(KnowledgeBase.uploaded_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def list_by_category(self, session: AsyncSession, category: str | None) -> list[KnowledgeBase]:
        query = select(KnowledgeBase)
        query = (
            query.where(KnowledgeBase.category.is_(None))
            if category is None
            else query.where(KnowledgeBase.category == category)
        )
        query = query.order_by(KnowledgeBase.uploaded_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def list_categories(self, session: AsyncSession) -> list[str]:
        result = await session.execute(
            select(KnowledgeBase.category)
            .where(KnowledgeBase.category.is_not(None))
            .distinct()
            .order_by(KnowledgeBase.category.asc())
        )
        return [c for c in result.scalars().all() if c is not None]

    async def search(self, session: AsyncSession, keyword: str) -> list[KnowledgeBase]:
        pattern = f"%{keyword}%"
        result = await session.execute(
            select(KnowledgeBase)
            .where(
                or_(
                    KnowledgeBase.name.ilike(pattern),
                    KnowledgeBase.original_filename.ilike(pattern),
                )
            )
            .order_by(KnowledgeBase.uploaded_at.desc())
        )
        return list(result.scalars().all())

    async def count_all(self, session: AsyncSession) -> int:
        result = await session.execute(select(func.count()).select_from(KnowledgeBase))
        return int(result.scalar() or 0)

    async def sum_access_count(self, session: AsyncSession) -> int:
        result = await session.execute(select(func.coalesce(func.sum(KnowledgeBase.access_count), 0)))
        return int(result.scalar() or 0)

    async def count_by_vector_status(self, session: AsyncSession, status: str) -> int:
        result = await session.execute(
            select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.vector_status == status)
        )
        return int(result.scalar() or 0)

    async def delete(self, session: AsyncSession, kb: KnowledgeBase) -> None:
        await session.delete(kb)

    async def update_vector_status(
        self, session: AsyncSession, kb: KnowledgeBase, status: str, error: str | None = None
    ) -> None:
        kb.vector_status = status
        kb.vector_error = error
        await session.flush()

    async def update_category(self, session: AsyncSession, kb: KnowledgeBase, category: str | None) -> None:
        kb.category = category
        await session.flush()

    async def mark_vectorized(self, session: AsyncSession, kb: KnowledgeBase, job_id: str, chunk_count: int) -> None:
        kb.vector_job_id = job_id
        kb.chunk_count = chunk_count
        kb.vectorized_at = datetime.now(UTC)
        await session.flush()
