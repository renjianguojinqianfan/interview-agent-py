from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.rag_chat import RagChatMessage, RagChatSession


class RagChatRepository:
    """RAG 问答会话与消息的异步仓储。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def get_by_id(self, session: AsyncSession, pk: int) -> RagChatSession | None:
        result = await session.execute(select(RagChatSession).where(RagChatSession.id == pk))
        return result.scalar_one_or_none()

    async def save(self, session: AsyncSession, entity: RagChatSession) -> RagChatSession:
        session.add(entity)
        await session.flush()
        return entity

    async def list_all(self, session: AsyncSession) -> list[RagChatSession]:
        result = await session.execute(
            select(RagChatSession).order_by(RagChatSession.pinned.desc(), RagChatSession.updated_at.desc())
        )
        return list(result.scalars().all())

    async def delete(self, session: AsyncSession, entity: RagChatSession) -> None:
        await session.delete(entity)

    async def update_pinned(self, session: AsyncSession, entity: RagChatSession, pinned: bool) -> None:
        entity.pinned = pinned
        await session.flush()

    async def update_title(self, session: AsyncSession, entity: RagChatSession, title: str) -> None:
        entity.title = title
        await session.flush()

    async def count_messages(self, session: AsyncSession, session_pk: int) -> int:
        result = await session.execute(
            select(func.count()).select_from(RagChatMessage).where(RagChatMessage.session_id == session_pk)
        )
        return int(result.scalar() or 0)

    async def add_message(self, session: AsyncSession, message: RagChatMessage) -> RagChatMessage:
        session.add(message)
        await session.flush()
        return message

    async def count_messages_by_role(self, session: AsyncSession, role: str) -> int:
        result = await session.execute(
            select(func.count()).select_from(RagChatMessage).where(RagChatMessage.role == role)
        )
        return int(result.scalar() or 0)

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
