"""面试日程领域实体：纯 StrEnum + dataclass，零框架依赖。

对应 Java 的 InterviewStatus 枚举。ORM 模型在 infrastructure/db/models/interview_schedule.py。
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class InterviewStatus(StrEnum):
    """真实面试日程状态机。

    PENDING -> COMPLETED（手动完成）
    PENDING -> CANCELLED（手动取消或定时任务过期取消）
    PENDING -> RESCHEDULED（手动改期）

    无转换方向校验，与 Java 行为一致。
    """

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"


@dataclass(frozen=True)
class ParsedSchedule:
    """规则解析或 LLM 解析的中间结果（domain 视角）。

    company_name / position / interview_time 为必需字段，None 表示未提取到。
    """

    company_name: str | None
    position: str | None
    interview_time: datetime | None
    interview_type: str | None = None
    meeting_link: str | None = None
    round_number: int = 1
    interviewer: str | None = None
    notes: str | None = None
