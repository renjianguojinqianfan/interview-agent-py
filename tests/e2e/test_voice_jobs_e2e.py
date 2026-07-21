"""语音定时任务真实 Postgres 端到端（#20 AC2：pause_idle / cleanup_zombie）。

补齐 3 个定时任务中的语音两项：真库插入受控 updated_at 的会话，跑真实 job，
断言 aware UTC 阈值比较与批量状态流转正确（兼作 G.3 voice 表 timestamptz 回归）。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.entities.voice_interview import VoiceSessionStatus
from app.infrastructure.db.models.voice_interview import VoiceInterviewSession
from app.infrastructure.scheduler.jobs import cleanup_voice_zombie_sessions, pause_idle_voice_sessions


def _session(**overrides: object) -> VoiceInterviewSession:
    fields: dict[str, object] = {
        "role_type": "Java面试官",
        "status": VoiceSessionStatus.IN_PROGRESS.value,
    }
    fields.update(overrides)
    return VoiceInterviewSession(**fields)


async def _all_sessions(factory: async_sessionmaker) -> list[VoiceInterviewSession]:
    async with factory() as session:
        result = await session.execute(select(VoiceInterviewSession).order_by(VoiceInterviewSession.id))
        return list(result.scalars().all())


async def test_pause_idle_voice_sessions_e2e(live_session_factory: async_sessionmaker) -> None:
    """IN_PROGRESS 且 updated_at 早于暂停超时阈值 -> PAUSED；活跃会话保留。"""
    async with live_session_factory() as session:
        session.add(_session(updated_at=datetime.now(UTC) - timedelta(minutes=10)))  # 空闲超时
        session.add(_session(updated_at=datetime.now(UTC)))  # 活跃
        await session.commit()

    await pause_idle_voice_sessions(live_session_factory)

    rows = await _all_sessions(live_session_factory)
    assert rows[0].status == VoiceSessionStatus.PAUSED.value
    assert rows[1].status == VoiceSessionStatus.IN_PROGRESS.value


async def test_cleanup_zombie_sessions_e2e(live_session_factory: async_sessionmaker) -> None:
    """IN_PROGRESS 超时僵尸 -> COMPLETED；PROCESSING 卡住评估 -> FAILED。"""
    async with live_session_factory() as session:
        session.add(_session(updated_at=datetime.now(UTC) - timedelta(hours=3)))  # 僵尸会话
        session.add(
            _session(
                status=VoiceSessionStatus.COMPLETED.value,
                evaluate_status=AsyncTaskStatus.PROCESSING.value,
                updated_at=datetime.now(UTC) - timedelta(hours=3),
            )
        )  # 卡住的评估
        await session.commit()

    await cleanup_voice_zombie_sessions(live_session_factory)

    rows = await _all_sessions(live_session_factory)
    assert rows[0].status == VoiceSessionStatus.COMPLETED.value
    assert rows[1].evaluate_status == AsyncTaskStatus.FAILED.value
