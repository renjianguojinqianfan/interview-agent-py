from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.entities.voice_interview import InterviewPhase, VoiceSessionStatus
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewEvaluation as VoiceInterviewEvaluationORM,
)
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewMessage as VoiceInterviewMessageORM,
)
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewSession as VoiceInterviewSessionORM,
)

_EVAL_TIMEOUT_ERROR = "评估超时，请重新触发"


class VoiceInterviewRepository:
    """语音面试会话/消息/评估的异步仓储。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def save_session(
        self,
        session: AsyncSession,
        voice_session: VoiceInterviewSessionORM,
    ) -> VoiceInterviewSessionORM:
        session.add(voice_session)
        await session.flush()
        return voice_session

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: int,
    ) -> VoiceInterviewSessionORM | None:
        result = await session.execute(
            select(VoiceInterviewSessionORM).where(VoiceInterviewSessionORM.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        session: AsyncSession,
        user_id: str,
        status: str | None = None,
    ) -> list[VoiceInterviewSessionORM]:
        query = select(VoiceInterviewSessionORM).where(VoiceInterviewSessionORM.user_id == user_id)
        if status is not None:
            query = query.where(VoiceInterviewSessionORM.status == status)
        query = query.order_by(VoiceInterviewSessionORM.updated_at.desc())
        result = await session.execute(query)
        return list(result.scalars().all())

    async def delete(
        self,
        session: AsyncSession,
        voice_session: VoiceInterviewSessionORM,
    ) -> None:
        await session.delete(voice_session)

    async def update_evaluate_status(
        self,
        session: AsyncSession,
        voice_session: VoiceInterviewSessionORM,
        status: str,
        error: str | None = None,
    ) -> None:
        voice_session.evaluate_status = status
        voice_session.evaluate_error = error
        await session.flush()

    async def update_current_phase(
        self,
        session: AsyncSession,
        voice_session: VoiceInterviewSessionORM,
        phase: str,
    ) -> None:
        """更新会话当前阶段（阶段自动切换 #17）。"""
        voice_session.current_phase = phase
        await session.flush()

    async def pause_session(
        self,
        session: AsyncSession,
        voice_session: VoiceInterviewSessionORM,
    ) -> None:
        """将单个会话置 PAUSED（WS 暂停超时触发）。"""
        voice_session.status = VoiceSessionStatus.PAUSED.value
        voice_session.paused_at = datetime.now(UTC)
        await session.flush()

    async def save_message(
        self,
        session: AsyncSession,
        message: VoiceInterviewMessageORM,
    ) -> VoiceInterviewMessageORM:
        session.add(message)
        await session.flush()
        return message

    async def find_messages_by_session(
        self,
        session: AsyncSession,
        session_pk: int,
    ) -> list[VoiceInterviewMessageORM]:
        result = await session.execute(
            select(VoiceInterviewMessageORM)
            .where(VoiceInterviewMessageORM.session_id == session_pk)
            .order_by(VoiceInterviewMessageORM.sequence_num)
        )
        return list(result.scalars().all())

    async def count_messages_by_session(
        self,
        session: AsyncSession,
        session_pk: int,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(VoiceInterviewMessageORM)
            .where(VoiceInterviewMessageORM.session_id == session_pk)
        )
        return int(result.scalar() or 0)

    async def count_messages_by_sessions(
        self,
        session: AsyncSession,
        session_pks: list[int],
    ) -> dict[int, int]:
        """按会话主键分组统计消息数（一次查询），用于会话列表 messageCount（避 N+1）。"""
        if not session_pks:
            return {}
        result = await session.execute(
            select(VoiceInterviewMessageORM.session_id, func.count())
            .where(VoiceInterviewMessageORM.session_id.in_(session_pks))
            .group_by(VoiceInterviewMessageORM.session_id)
        )
        return {int(sid): int(count) for sid, count in result.all()}

    async def find_latest_unanswered_message(
        self,
        session: AsyncSession,
        session_pk: int,
    ) -> VoiceInterviewMessageORM | None:
        """最近一条已提问(ai_generated_text 非空)但未作答(user_recognized_text 为空)的消息（回填目标）。

        对齐 Java findFirstBySessionIdAndUserRecognizedTextIsNullAndAiGeneratedTextIsNotNullOrderBySequenceNumDesc。
        """
        result = await session.execute(
            select(VoiceInterviewMessageORM)
            .where(VoiceInterviewMessageORM.session_id == session_pk)
            .where(VoiceInterviewMessageORM.user_recognized_text.is_(None))
            .where(VoiceInterviewMessageORM.ai_generated_text.is_not(None))
            .order_by(VoiceInterviewMessageORM.sequence_num.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_evaluation_by_session(
        self,
        session: AsyncSession,
        session_pk: int,
    ) -> VoiceInterviewEvaluationORM | None:
        result = await session.execute(
            select(VoiceInterviewEvaluationORM).where(VoiceInterviewEvaluationORM.session_id == session_pk)
        )
        return result.scalar_one_or_none()

    async def save_evaluation(
        self,
        session: AsyncSession,
        evaluation: VoiceInterviewEvaluationORM,
    ) -> VoiceInterviewEvaluationORM:
        session.add(evaluation)
        await session.flush()
        return evaluation

    async def bulk_pause_idle_in_progress(
        self,
        session: AsyncSession,
        threshold: datetime,
    ) -> int:
        """将 IN_PROGRESS 且 updated_at 早于 threshold 的会话置 PAUSED（暂停超时检查，30s 触发）。"""
        result = await session.execute(
            update(VoiceInterviewSessionORM)
            .where(VoiceInterviewSessionORM.status == VoiceSessionStatus.IN_PROGRESS.value)
            .where(VoiceInterviewSessionORM.updated_at < threshold)
            .values(status=VoiceSessionStatus.PAUSED.value, paused_at=func.now())
        )
        return cast(int, getattr(result, "rowcount", 0))

    async def bulk_complete_zombie_sessions(
        self,
        session: AsyncSession,
        threshold: datetime,
    ) -> int:
        """将 IN_PROGRESS 且 updated_at 早于 threshold 的僵尸会话置 COMPLETED（僵尸清理，5min 触发）。"""
        result = await session.execute(
            update(VoiceInterviewSessionORM)
            .where(VoiceInterviewSessionORM.status == VoiceSessionStatus.IN_PROGRESS.value)
            .where(VoiceInterviewSessionORM.updated_at < threshold)
            .values(
                status=VoiceSessionStatus.COMPLETED.value,
                end_time=func.now(),
                current_phase=InterviewPhase.COMPLETED.value,
            )
        )
        return cast(int, getattr(result, "rowcount", 0))

    async def bulk_fail_stuck_evaluations(
        self,
        session: AsyncSession,
        threshold: datetime,
    ) -> int:
        """将 evaluate_status=PROCESSING 且 updated_at 早于 threshold 的评估置 FAILED（僵尸清理，5min 触发）。"""
        result = await session.execute(
            update(VoiceInterviewSessionORM)
            .where(VoiceInterviewSessionORM.evaluate_status == AsyncTaskStatus.PROCESSING.value)
            .where(VoiceInterviewSessionORM.updated_at < threshold)
            .values(evaluate_status=AsyncTaskStatus.FAILED.value, evaluate_error=_EVAL_TIMEOUT_ERROR)
        )
        return cast(int, getattr(result, "rowcount", 0))
