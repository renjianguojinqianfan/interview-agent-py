"""会话状态机校验：纯函数，零框架依赖。

合法迁移：CREATED -> IN_PROGRESS、CREATED -> COMPLETED、IN_PROGRESS -> COMPLETED。
EVALUATED 为终态（由 #9 评估消费侧置位），#8 不产生该状态。
"""

from app.domain.entities.interview import SessionStatus
from app.domain.errors import BusinessException, ErrorCode

_VALID_TRANSITIONS: set[tuple[SessionStatus, SessionStatus]] = {
    (SessionStatus.CREATED, SessionStatus.IN_PROGRESS),
    (SessionStatus.CREATED, SessionStatus.COMPLETED),
    (SessionStatus.IN_PROGRESS, SessionStatus.COMPLETED),
}


def validate_transition(current: SessionStatus, target: SessionStatus) -> None:
    """校验状态迁移合法性，非法则抛 BusinessException。"""
    if (current, target) in _VALID_TRANSITIONS:
        return
    if current in (SessionStatus.COMPLETED, SessionStatus.EVALUATED) and target == SessionStatus.COMPLETED:
        raise BusinessException(ErrorCode.INTERVIEW_ALREADY_COMPLETED)
    raise BusinessException(ErrorCode.BAD_REQUEST, f"非法状态迁移: {current} -> {target}")


def is_unfinished(status: SessionStatus) -> bool:
    """CREATED 或 IN_PROGRESS 视为未完成。"""
    return status in (SessionStatus.CREATED, SessionStatus.IN_PROGRESS)
