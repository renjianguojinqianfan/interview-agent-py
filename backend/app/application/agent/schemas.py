"""自适应面试 Agent 请求/响应 DTO。"""

from typing import Any

from pydantic import BaseModel, Field

from app.api.responses import BaseSchema


class CreateAdaptiveSessionRequest(BaseSchema):
    """创建自适应面试会话请求。"""

    skill_id: str = "java-backend"
    difficulty: str = "mid"
    resume_text: str = ""
    max_turns: int = Field(default=6, ge=3, le=20)
    llm_provider: str | None = None


class SubmitAdaptiveAnswerRequest(BaseSchema):
    """提交自适应面试答案请求。"""

    answer: str


class AdaptiveQuestionDTO(BaseModel):
    """当前面试题。"""

    question: str
    category: str
    difficulty: str
    question_index: int


class AdaptiveSessionDTO(BaseModel):
    """自适应面试会话状态。"""

    session_id: str
    skill_id: str
    difficulty: str
    turn_count: int
    max_turns: int
    current_question: AdaptiveQuestionDTO | None = None
    finished: bool = False
    category_scores: dict[str, float] = Field(default_factory=dict)
    decision_trace: list[dict[str, object]] | None = None


class AdaptiveAnswerResultDTO(BaseModel):
    """提交答案后的响应。"""

    score: int | None = None
    feedback: str | None = None
    next_question: AdaptiveQuestionDTO | None = None
    finished: bool = False
    difficulty_changed: bool = False
    new_difficulty: str | None = None


class AdaptiveReportDTO(BaseModel):
    """面试最终报告。"""

    session_id: str
    total_questions: int
    overall_score: int
    category_scores: dict[str, int] = Field(default_factory=dict)
    questions: list[dict[str, Any]] = Field(default_factory=list)
    difficulty_progression: str = "mid"
