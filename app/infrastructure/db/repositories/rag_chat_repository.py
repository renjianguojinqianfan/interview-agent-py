from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.rag_chat import RagChatMessage, RagChatSession


class RagChatRepository:
    """RAG 问答会话与消息的异步仓储。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def get_by_session_id(self, session: AsyncSession, session_id: str) -> RagChatSession | None:
        result = await session.execute(select(RagChatSession).where(RagChatSession.session_id == session_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, session: AsyncSession, pk: int) -> RagChatSession | None:
        result = await session.execute(select(RagChatSession).where(RagChatSession.id == pk))
        return result.scalar_one_or_none()

    async def save(self, session: AsyncSession, entity: RagChatSession) -> RagChatSession:
        session.add(entity)
        await session.flush()
        return entity

    async def list_paginated(self, session: AsyncSession, page: int, size: int) -> tuple[list[RagChatSession], int]:
        offset = (page - 1) * size
        items_result = await session.execute(
            select(RagChatSession)
            .order_by(RagChatSession.pinned.desc(), RagChatSession.updated_at.desc())
            .offset(offset)
            .limit(size)
        )
        items = list(items_result.scalars().all())

        count_result = await session.execute(select(func.count()).select_from(RagChatSession))
        total = int(count_result.scalar() or 0)

        return items, total

    async def delete(self, session: AsyncSession, entity: RagChatSession) -> None:
        await session.delete(entity)

    async def update_pinned(self, session: AsyncSession, entity: RagChatSession, pinned: bool) -> None:
        entity.pinned = pinned
        await session.flush()

    async def add_message(self, session: AsyncSession, message: RagChatMessage) -> RagChatMessage:
        session.add(message)
        await session.flush()
        return message

    async def list_messages(self, session: AsyncSession, session_pk: int) -> list[RagChatMessage]:
        result = await session.execute(
            select(RagChatMessage)
            .where(RagChatMessage.session_id == session_pk)
            .order_by(RagChatMessage.created_at.asc(), RagChatMessage.id.asc())
        )
        return list(result.scalars().all())

    async def recent_history(self, session: AsyncSession, session_pk: int, limit: int) -> list[RagChatMessage]:
        result = await session.execute(
            select(RagChatMessage)
            .where(RagChatMessage.session_id == session_pk)
            .order_by(RagChatMessage.created_at.desc(), RagChatMessage.id.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()
        return messages
