"""文字面试领域实体：纯 dataclass + enum，零框架依赖。

对应 Java 的 InterviewSessionDTO/InterviewQuestionDTO/InterviewAnswerEntity/HistoricalQuestion。
ORM 模型在 infrastructure/db/models/interview.py，与本实体分离。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SessionStatus(StrEnum):
    """文字面试会话生命周期：CREATED -> IN_PROGRESS -> COMPLETED -> EVALUATED。

    EVALUATED 由 #9 评估消费侧置位，#8 只覆盖前三个状态。
    """

    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EVALUATED = "EVALUATED"


@dataclass(frozen=True)
class InterviewQuestion:
    """面试问题（含追问）。type 由 Skill category key 驱动（如 MYSQL、CSS）。"""

    question_index: int
    question: str
    type: str
    category: str
    topic_summary: str | None = None
    user_answer: str | None = None
    score: int | None = None
    feedback: str | None = None
    is_follow_up: bool = False
    parent_question_index: int | None = None

    def with_answer(self, answer: str) -> "InterviewQuestion":
        return InterviewQuestion(
            question_index=self.question_index,
            question=self.question,
            type=self.type,
            category=self.category,
            topic_summary=self.topic_summary,
            user_answer=answer,
            score=self.score,
            feedback=self.feedback,
            is_follow_up=self.is_follow_up,
            parent_question_index=self.parent_question_index,
        )


@dataclass(frozen=True)
class InterviewAnswer:
    """面试答案（domain 视角，非 ORM）。"""

    question_index: int
    question: str
    category: str
    user_answer: str
    score: int | None = None
    feedback: str | None = None


@dataclass(frozen=True)
class HistoricalQuestion:
    """历史提问去重用结构，仅取主问题（非追问）。"""

    question: str
    type: str | None
    topic_summary: str | None


@dataclass(frozen=True)
class InterviewSession:
    """面试会话（domain 视角，非 ORM）。

    questions 为 domain 实体列表，序列化/反序列化由 infrastructure 层负责。
    """

    session_id: str
    resume_id: int | None
    resume_text: str
    skill_id: str
    difficulty: str
    total_questions: int
    current_question_index: int
    status: SessionStatus
    questions: list[InterviewQuestion] = field(default_factory=list)
    llm_provider: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


# ==================== 出题常量（单一真相源）====================

MAX_FOLLOW_UP = 2
"""每个主问题最多追问数。"""

RESUME_QUESTION_RATIO = 0.6
"""有简历时简历题占比（60%），方向题占 40%。"""

DEFAULT_FOLLOW_UP_COUNT = 1
"""LLM 出题时每个主问题默认生成的追问数。"""

MAX_HISTORICAL_QUESTIONS = 60
"""历史题去重后保留的最大条数。"""

MIN_QUESTION_COUNT = 3
"""单次面试最少题数。"""

MAX_QUESTION_COUNT = 20
"""单次面试最多题数。"""

DEFAULT_DIFFICULTY = "mid"
"""默认难度。"""

DEFAULT_SKILL_ID = "java-backend"
"""默认技能 ID。"""

SESSION_TTL_SECONDS = 24 * 60 * 60
"""Redis 会话缓存 TTL：24 小时。"""

SESSION_ID_LENGTH = 16
"""sessionId 长度（uuid4 hex 截断）。"""

_DEFAULT_FALLBACK_QUESTIONS: tuple[str, ...] = (
    "请介绍你最熟悉的一个项目，包括你的角色、技术选型与主要贡献。",
    "在最近的工作中，你遇到的最有挑战性的技术问题是什么？你是如何定位和解决的？",
    "请谈谈你对系统设计中可用性与一致性权衡的理解，并举一个实际例子。",
    "如果让你从零设计一个高并发的接口服务，你会从哪些维度考虑？关键瓶颈在哪里？",
    "请回顾过去一年你最有成就感的一次技术决策，为什么它是对的？事后有无改进空间？",
)
"""LLM 出题全失败时的兜底通用题（5 道），用于 generate_fallback_questions。"""


def get_default_fallback_questions() -> tuple[str, ...]:
    """返回兜底通用题元组（只读，避免外部修改常量）。"""
    return _DEFAULT_FALLBACK_QUESTIONS
