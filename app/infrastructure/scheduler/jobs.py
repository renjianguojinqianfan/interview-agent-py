"""定时任务定义。

每个 job 函数接收 session_factory 参数，内部管理 session 生命周期。
#18 将在此模块追加暂停超时检查、僵尸会话清理等任务。
"""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.repositories.interview_schedule_repository import InterviewScheduleRepository

logger = logging.getLogger(__name__)


async def cancel_expired_schedules(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """将所有 PENDING 且面试时间早于当前的日程标记为 CANCELLED。

    每小时由 SchedulerManager 触发。
    """
    async with session_factory() as session:
        repository = InterviewScheduleRepository()
        now = datetime.now()
        count = await repository.cancel_expired(session, now)
        await session.commit()
        if count > 0:
            logger.info("已将 %d 条过期面试标记为已取消", count)
