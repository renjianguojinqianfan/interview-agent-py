"""语音面试领域实体：纯 enum + dataclass + 常量，零框架依赖。

对应 Java 的 VoiceInterviewSessionStatus / InterviewPhase / VoiceInterviewMessageEntity。
ORM 模型在 infrastructure/db/models/voice_interview.py，与本实体分离。
"""

from dataclasses import dataclass
from enum import StrEnum


class VoiceSessionStatus(StrEnum):
    """语音面试会话状态机。

    IN_PROGRESS -> PAUSED（用户/超时暂停）
    PAUSED -> IN_PROGRESS（恢复）
    IN_PROGRESS / PAUSED -> COMPLETED（结束）
    IN_PROGRESS / PAUSED -> FAILED（异常）
    COMPLETED / FAILED 为终态。
    """

    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class InterviewPhase(StrEnum):
    """语音面试阶段：INTRO -> TECH -> PROJECT -> HR -> COMPLETED。

    阶段动态切换规则（shouldTransitionToNextPhase）由 #17 实现，#14 仅定义枚举与配置。
    """

    INTRO = "INTRO"
    TECH = "TECH"
    PROJECT = "PROJECT"
    HR = "HR"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class PhaseConfig:
    """单个面试阶段的时长与题数约束（附录 F）。"""

    phase: InterviewPhase
    min_duration_seconds: int
    suggested_duration_seconds: int
    max_duration_seconds: int
    min_questions: int
    max_questions: int


PHASE_CONFIGS: dict[InterviewPhase, PhaseConfig] = {
    InterviewPhase.INTRO: PhaseConfig(
        phase=InterviewPhase.INTRO,
        min_duration_seconds=3 * 60,
        suggested_duration_seconds=5 * 60,
        max_duration_seconds=8 * 60,
        min_questions=2,
        max_questions=5,
    ),
    InterviewPhase.TECH: PhaseConfig(
        phase=InterviewPhase.TECH,
        min_duration_seconds=8 * 60,
        suggested_duration_seconds=10 * 60,
        max_duration_seconds=15 * 60,
        min_questions=3,
        max_questions=8,
    ),
    InterviewPhase.PROJECT: PhaseConfig(
        phase=InterviewPhase.PROJECT,
        min_duration_seconds=8 * 60,
        suggested_duration_seconds=10 * 60,
        max_duration_seconds=15 * 60,
        min_questions=2,
        max_questions=5,
    ),
    InterviewPhase.HR: PhaseConfig(
        phase=InterviewPhase.HR,
        min_duration_seconds=3 * 60,
        suggested_duration_seconds=5 * 60,
        max_duration_seconds=8 * 60,
        min_questions=2,
        max_questions=5,
    ),
}


@dataclass(frozen=True)
class VoiceMessage:
    """语音面试消息（domain 视角，非 ORM）。

    一行存一对 QA：ai_generated_text 为 AI 提问，user_recognized_text 为用户作答。
    user_recognized_text 为 None 表示该题未作答（评估按 0 分处理）。
    """

    sequence_num: int
    phase: str
    ai_generated_text: str | None
    user_recognized_text: str | None


# ==================== 语音面试常量（单一真相源）====================

DEFAULT_USER_ID = "default"
"""默认用户 ID（ADR-0007 无认证，单用户场景）。"""

DEFAULT_SKILL_ID = "java-backend"
"""默认技能 ID。"""

DEFAULT_DIFFICULTY = "mid"
"""默认难度。"""

DEFAULT_ROLE_TYPE = "Java面试官"
"""默认面试官角色。"""

DEFAULT_PLANNED_DURATION_MINUTES = 30
"""默认计划时长（分钟）。"""

VOICE_SESSION_TTL_SECONDS = 60 * 60
"""Redis 语音会话缓存 TTL：1 小时（附录 F）。"""

PAUSE_IDLE_TIMEOUT_SECONDS = 5 * 60
"""IN_PROGRESS 会话空闲超时：超过则定时任务自动置 PAUSED（附录 F 5 分钟自动暂停）。"""

ZOMBIE_SESSION_TIMEOUT_SECONDS = 2 * 60 * 60
"""IN_PROGRESS 僵尸会话超时：超过则定时任务自动置 COMPLETED（对齐 Java cleanupStaleSessions 2h）。"""

EVAL_PROCESSING_TIMEOUT_SECONDS = 30 * 60
"""评估 PROCESSING 卡住超时：超过则定时任务置 FAILED（对齐 Java 30min）。"""

MESSAGE_TYPE_DIALOGUE = "DIALOGUE"
"""语音消息类型：对话（AI 提问 + 用户作答同行存储）。"""
