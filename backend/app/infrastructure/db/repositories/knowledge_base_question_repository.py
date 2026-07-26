from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.knowledge_base import KnowledgeBaseQuestion


class KnowledgeBaseQuestionRepository:
    """知识库题库异步仓储。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def list_by_knowledge_base(
        self, session: AsyncSession, kb_id: int, status: str | None = None
    ) -> list[KnowledgeBaseQuestion]:
        query = select(KnowledgeBaseQuestion).where(KnowledgeBaseQuestion.knowledge_base_id == kb_id)
        if status is not None:
            query = query.where(KnowledgeBaseQuestion.status == status)
        query = query.order_by(KnowledgeBaseQuestion.updated_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def category_counts(self, session: AsyncSession, kb_id: int) -> list[tuple[str, int]]:
        """各方向题目数，按题数降序、方向名升序（对齐 Java findCategoryCounts），排除空方向。"""
        result = await session.execute(
            select(KnowledgeBaseQuestion.category, func.count())
            .where(
                KnowledgeBaseQuestion.knowledge_base_id == kb_id,
                KnowledgeBaseQuestion.category.is_not(None),
                KnowledgeBaseQuestion.category != "",
            )
            .group_by(KnowledgeBaseQuestion.category)
            .order_by(func.count().desc(), KnowledgeBaseQuestion.category.asc())
        )
        return [(category, int(count)) for category, count in result.all() if category is not None]

    async def get_by_id(self, session: AsyncSession, question_id: int) -> KnowledgeBaseQuestion | None:
        result = await session.execute(select(KnowledgeBaseQuestion).where(KnowledgeBaseQuestion.id == question_id))
        return result.scalar_one_or_none()

    async def find_recent_questions(
        self, session: AsyncSession, kb_id: int, difficulty: str, limit: int
    ) -> list[KnowledgeBaseQuestion]:
        """同知识库 + 难度的最近题目（updated_at 倒序），供生成提示词注入去重参照。"""
        result = await session.execute(
            select(KnowledgeBaseQuestion)
            .where(
                KnowledgeBaseQuestion.knowledge_base_id == kb_id,
                KnowledgeBaseQuestion.difficulty == difficulty,
            )
            .order_by(KnowledgeBaseQuestion.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_active_questions(
        self, session: AsyncSession, kb_id: int, difficulty: str, category: str | None = None
    ) -> list[KnowledgeBaseQuestion]:
        """组卷候选：ACTIVE + 难度（category 可选），updated_at 倒序（对齐 Java selectActiveQuestions）。"""
        query = select(KnowledgeBaseQuestion).where(
            KnowledgeBaseQuestion.knowledge_base_id == kb_id,
            KnowledgeBaseQuestion.difficulty == difficulty,
            KnowledgeBaseQuestion.status == "ACTIVE",
        )
        if category is not None:
            query = query.where(KnowledgeBaseQuestion.category == category)
        result = await session.execute(query.order_by(KnowledgeBaseQuestion.updated_at.desc()))
        return list(result.scalars().all())

    async def save(self, session: AsyncSession, question: KnowledgeBaseQuestion) -> KnowledgeBaseQuestion:
        session.add(question)
        await session.flush()
        return question

    async def save_all(self, session: AsyncSession, questions: list[KnowledgeBaseQuestion]) -> None:
        session.add_all(questions)
        await session.flush()

    async def delete_by_knowledge_base_id(self, session: AsyncSession, kb_id: int) -> None:
        await session.execute(delete(KnowledgeBaseQuestion).where(KnowledgeBaseQuestion.knowledge_base_id == kb_id))

    async def delete(self, session: AsyncSession, question: KnowledgeBaseQuestion) -> None:
        await session.delete(question)
