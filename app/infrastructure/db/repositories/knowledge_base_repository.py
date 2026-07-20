from datetime import datetime

from sqlalchemy import func, select
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

    async def list_paginated(self, session: AsyncSession, page: int, size: int) -> tuple[list[KnowledgeBase], int]:
        offset = (page - 1) * size
        items_result = await session.execute(
            select(KnowledgeBase).order_by(KnowledgeBase.uploaded_at.desc()).offset(offset).limit(size)
        )
        items = list(items_result.scalars().all())

        count_result = await session.execute(select(func.count()).select_from(KnowledgeBase))
        total = int(count_result.scalar() or 0)

        return items, total

    async def delete(self, session: AsyncSession, kb: KnowledgeBase) -> None:
        await session.delete(kb)

    async def update_vector_status(
        self, session: AsyncSession, kb: KnowledgeBase, status: str, error: str | None = None
    ) -> None:
        kb.vector_status = status
        kb.vector_error = error
        await session.flush()

    async def mark_vectorized(self, session: AsyncSession, kb: KnowledgeBase, job_id: str, chunk_count: int) -> None:
        kb.vector_job_id = job_id
        kb.chunk_count = chunk_count
        kb.vectorized_at = datetime.now()
        await session.flush()
