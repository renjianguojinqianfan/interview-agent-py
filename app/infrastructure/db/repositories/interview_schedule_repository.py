from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.interview_schedule import InterviewStatus
from app.infrastructure.db.models.interview_schedule import InterviewSchedule


class InterviewScheduleRepository:
    """面试日程异步仓储。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def save(self, session: AsyncSession, schedule: InterviewSchedule) -> InterviewSchedule:
        session.add(schedule)
        await session.flush()
        return schedule

    async def get_by_id(self, session: AsyncSession, schedule_id: int) -> InterviewSchedule | None:
        result = await session.execute(select(InterviewSchedule).where(InterviewSchedule.id == schedule_id))
        return result.scalar_one_or_none()

    async def list_all(self, session: AsyncSession) -> list[InterviewSchedule]:
        result = await session.execute(select(InterviewSchedule).order_by(InterviewSchedule.interview_time))
        return list(result.scalars().all())

    async def list_by_status(self, session: AsyncSession, status: str) -> list[InterviewSchedule]:
        result = await session.execute(
            select(InterviewSchedule)
            .where(InterviewSchedule.status == status)
            .order_by(InterviewSchedule.interview_time)
        )
        return list(result.scalars().all())

    async def list_by_time_range(
        self, session: AsyncSession, start: datetime, end: datetime
    ) -> list[InterviewSchedule]:
        result = await session.execute(
            select(InterviewSchedule)
            .where(InterviewSchedule.interview_time >= start)
            .where(InterviewSchedule.interview_time <= end)
            .order_by(InterviewSchedule.interview_time)
        )
        return list(result.scalars().all())

    async def delete(self, session: AsyncSession, schedule: InterviewSchedule) -> None:
        await session.delete(schedule)

    async def cancel_expired(self, session: AsyncSession, now: datetime) -> int:
        """将所有 PENDING 且面试时间早于 now 的日程标记为 CANCELLED。

        返回受影响行数。
        """
        result = await session.execute(
            update(InterviewSchedule)
            .where(InterviewSchedule.status == InterviewStatus.PENDING.value)
            .where(InterviewSchedule.interview_time < now)
            .values(status=InterviewStatus.CANCELLED.value)
        )
        return cast(int, getattr(result, "rowcount", 0))
