from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.resume import Resume, ResumeAnalysis


class ResumeRepository:
    """简历与简历分析结果的异步仓储。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def find_by_hash(self, session: AsyncSession, file_hash: str) -> Resume | None:
        result = await session.execute(select(Resume).where(Resume.file_hash == file_hash))
        return result.scalar_one_or_none()

    async def get_by_id(self, session: AsyncSession, resume_id: int) -> Resume | None:
        result = await session.execute(select(Resume).where(Resume.id == resume_id))
        return result.scalar_one_or_none()

    async def save(self, session: AsyncSession, resume: Resume) -> Resume:
        session.add(resume)
        await session.flush()
        return resume

    async def list_all(self, session: AsyncSession) -> list[Resume]:
        result = await session.execute(select(Resume).order_by(Resume.uploaded_at.desc()))
        return list(result.scalars().all())

    async def count_all(self, session: AsyncSession) -> int:
        result = await session.execute(select(func.count()).select_from(Resume))
        return int(result.scalar() or 0)

    async def sum_access_count(self, session: AsyncSession) -> int:
        result = await session.execute(select(func.coalesce(func.sum(Resume.access_count), 0)))
        return int(result.scalar() or 0)

    async def delete(self, session: AsyncSession, resume: Resume) -> None:
        await session.delete(resume)

    async def update_analyze_status(
        self, session: AsyncSession, resume: Resume, status: str, error: str | None = None
    ) -> None:
        resume.analyze_status = status
        resume.analyze_error = error
        await session.flush()

    async def save_analysis(self, session: AsyncSession, analysis: ResumeAnalysis) -> ResumeAnalysis:
        session.add(analysis)
        await session.flush()
        return analysis

    async def increment_access_count(self, session: AsyncSession, resume: Resume) -> None:
        resume.access_count += 1
        resume.last_accessed_at = datetime.now(UTC)
        await session.flush()

    async def find_latest_analysis(self, session: AsyncSession, resume_id: int) -> ResumeAnalysis | None:
        result = await session.execute(
            select(ResumeAnalysis)
            .where(ResumeAnalysis.resume_id == resume_id)
            .order_by(ResumeAnalysis.analyzed_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def find_analyses_by_resume_id(self, session: AsyncSession, resume_id: int) -> list[ResumeAnalysis]:
        result = await session.execute(
            select(ResumeAnalysis)
            .where(ResumeAnalysis.resume_id == resume_id)
            .order_by(ResumeAnalysis.analyzed_at.desc())
        )
        return list(result.scalars().all())

    async def delete_analyses_by_resume_id(self, session: AsyncSession, resume_id: int) -> int:
        result = await session.execute(delete(ResumeAnalysis).where(ResumeAnalysis.resume_id == resume_id))
        return int(getattr(result, "rowcount", 0) or 0)
