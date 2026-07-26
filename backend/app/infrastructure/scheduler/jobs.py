"""定时任务定义。

每个 job 函数接收 session_factory 参数，内部管理 session 生命周期。
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.voice_interview import (
    EVAL_PROCESSING_TIMEOUT_SECONDS,
    PAUSE_IDLE_TIMEOUT_SECONDS,
    ZOMBIE_SESSION_TIMEOUT_SECONDS,
)
from app.infrastructure.db.repositories.interview_schedule_repository import InterviewScheduleRepository
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.db.repositories.voice_interview_repository import VoiceInterviewRepository

if TYPE_CHECKING:
    from app.application.knowledgebase.generation_state_service import QuestionGenerationStateService
    from app.infrastructure.tasks.question_gen_producer import QuestionGenProducer

logger = logging.getLogger(__name__)

# 题目生成恢复阈值（对齐 Java QuestionGenerationRecoveryScheduler）
QUEUED_STALE_MINUTES = 2
PROCESSING_STALE_MINUTES = 20


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


async def recover_stale_question_gen_tasks(
    session_factory: async_sessionmaker[AsyncSession],
    state_service: "QuestionGenerationStateService",
    producer: "QuestionGenProducer",
) -> None:
    """恢复未成功投递或执行节点异常退出的题目生成任务（与 xautoclaim 双保险）。

    每 60 秒由 SchedulerManager 触发：QUEUED 逾 2 分钟刷新时间戳后重投；
    PROCESSING 逾 20 分钟重置回 QUEUED 再重投。重投携原 taskId，消费侧原子领取去重。
    """
    from app.infrastructure.tasks.question_gen_producer import QuestionGenPayload

    now = datetime.now(UTC)
    repository = KnowledgeBaseRepository()

    queued_threshold = now - timedelta(minutes=QUEUED_STALE_MINUTES)
    async with session_factory() as session:
        stale_queued = await repository.find_stale_question_gen_tasks(session, "QUEUED", queued_threshold)
    for task in stale_queued:
        task_id = task.question_gen_task_id
        if task_id and await state_service.touch_queued_for_recovery(task.id, task_id, queued_threshold):
            await producer.send_task(QuestionGenPayload(kb_id=task.id, task_id=task_id))
            logger.info("重新投递等待中的题目生成任务: kbId=%s, taskId=%s", task.id, task_id)

    processing_threshold = now - timedelta(minutes=PROCESSING_STALE_MINUTES)
    async with session_factory() as session:
        stale_processing = await repository.find_stale_question_gen_tasks(session, "PROCESSING", processing_threshold)
    for task in stale_processing:
        task_id = task.question_gen_task_id
        if task_id and await state_service.reset_stale_processing(task.id, task_id, processing_threshold):
            await producer.send_task(QuestionGenPayload(kb_id=task.id, task_id=task_id))
            logger.warning("恢复卡住的题目生成任务: kbId=%s, taskId=%s", task.id, task_id)
