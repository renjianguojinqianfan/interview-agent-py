"""定时任务定义。

每个 job 函数接收 session_factory 参数，内部管理 session 生命周期。
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.voice_interview import (
    EVAL_PROCESSING_TIMEOUT_SECONDS,
    PAUSE_IDLE_TIMEOUT_SECONDS,
    ZOMBIE_SESSION_TIMEOUT_SECONDS,
)
from app.infrastructure.db.repositories.interview_schedule_repository import InterviewScheduleRepository
from app.infrastructure.db.repositories.voice_interview_repository import VoiceInterviewRepository

logger = logging.getLogger(__name__)


async def cancel_expired_schedules(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """将所有 PENDING 且面试时间早于当前的日程标记为 CANCELLED。

    每小时由 SchedulerManager 触发。
    """
    async with session_factory() as session:
        repository = InterviewScheduleRepository()
        now = datetime.now(UTC)
        count = await repository.cancel_expired(session, now)
        await session.commit()
        if count > 0:
            logger.info("已将 %d 条过期面试标记为已取消", count)


async def pause_idle_voice_sessions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """将 IN_PROGRESS 且 updated_at 早于暂停超时阈值的语音会话置 PAUSED。

    每 30 秒由 SchedulerManager 触发，作为 #15 WS 实时空闲超时（5min）的兜底。
    """
    async with session_factory() as session:
        repository = VoiceInterviewRepository()
        threshold = datetime.now(UTC) - timedelta(seconds=PAUSE_IDLE_TIMEOUT_SECONDS)
        count = await repository.bulk_pause_idle_in_progress(session, threshold)
        await session.commit()
        if count > 0:
            logger.info("已将 %d 个空闲语音会话自动暂停", count)


async def cleanup_voice_zombie_sessions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """清理语音面试僵尸会话：IN_PROGRESS 超 2h 置 COMPLETED + 评估 PROCESSING 卡 30min 置 FAILED。

    每 5 分钟由 SchedulerManager 触发，对齐 Java cleanupStaleSessions。
    """
    async with session_factory() as session:
        repository = VoiceInterviewRepository()
        now = datetime.now(UTC)
        zombie_count = await repository.bulk_complete_zombie_sessions(
            session, now - timedelta(seconds=ZOMBIE_SESSION_TIMEOUT_SECONDS)
        )
        stuck_count = await repository.bulk_fail_stuck_evaluations(
            session, now - timedelta(seconds=EVAL_PROCESSING_TIMEOUT_SECONDS)
        )
        await session.commit()
        if zombie_count > 0:
            logger.info("已将 %d 个僵尸语音会话标记为已完成", zombie_count)
        if stuck_count > 0:
            logger.info("已将 %d 个卡住的语音评估标记为失败", stuck_count)
