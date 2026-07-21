"""语音面试会话状态机校验：纯函数，零框架依赖。

合法迁移：
  IN_PROGRESS -> PAUSED（暂停）
  PAUSED -> IN_PROGRESS（恢复）
  IN_PROGRESS / PAUSED -> COMPLETED（结束）
  IN_PROGRESS / PAUSED -> FAILED（异常）
COMPLETED / FAILED 为终态，不允许迁出。
"""

from app.domain.entities.voice_interview import VoiceSessionStatus
from app.domain.errors import BusinessException, ErrorCode

_VALID_TRANSITIONS: set[tuple[VoiceSessionStatus, VoiceSessionStatus]] = {
    (VoiceSessionStatus.IN_PROGRESS, VoiceSessionStatus.PAUSED),
    (VoiceSessionStatus.PAUSED, VoiceSessionStatus.IN_PROGRESS),
    (VoiceSessionStatus.IN_PROGRESS, VoiceSessionStatus.COMPLETED),
    (VoiceSessionStatus.PAUSED, VoiceSessionStatus.COMPLETED),
    (VoiceSessionStatus.IN_PROGRESS, VoiceSessionStatus.FAILED),
    (VoiceSessionStatus.PAUSED, VoiceSessionStatus.FAILED),
}


def validate_transition(current: VoiceSessionStatus, target: VoiceSessionStatus) -> None:
    """校验状态迁移合法性，非法则抛 BusinessException(BAD_REQUEST)。"""
    if (current, target) in _VALID_TRANSITIONS:
        return
    raise BusinessException(ErrorCode.BAD_REQUEST, f"非法状态迁移: {current} -> {target}")


def is_unfinished(status: VoiceSessionStatus) -> bool:
    """IN_PROGRESS 或 PAUSED 视为未完成（可恢复或结束）。"""
    return status in (VoiceSessionStatus.IN_PROGRESS, VoiceSessionStatus.PAUSED)
