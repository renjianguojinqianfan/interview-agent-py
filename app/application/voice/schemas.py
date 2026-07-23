"""语音面试应用层 Pydantic schemas。

评估结果对外契约对齐复用的前端 `VoiceEvaluationDetail`（ADR-0001/0015）：
扁平 `answers[]`（由逐题明细 + 参考答案按 questionIndex 合并）+ sessionId + totalQuestions。
"""

from pydantic import Field

from app.api.responses import BaseSchema, NaiveIsoDatetime
from app.domain.entities.voice_interview import (
    DEFAULT_DIFFICULTY,
    DEFAULT_PLANNED_DURATION_MINUTES,
    DEFAULT_ROLE_TYPE,
    DEFAULT_SKILL_ID,
)


class CreateVoiceSessionRequest(BaseSchema):
    role_type: str = Field(default=DEFAULT_ROLE_TYPE, min_length=1)
    skill_id: str = Field(default=DEFAULT_SKILL_ID, min_length=1)
    difficulty: str = DEFAULT_DIFFICULTY
    resume_id: int | None = None
    custom_jd_text: str | None = None
    intro_enabled: bool = True
    tech_enabled: bool = True
    project_enabled: bool = True
    hr_enabled: bool = True
    llm_provider: str | None = None
    planned_duration: int = Field(default=DEFAULT_PLANNED_DURATION_MINUTES, ge=1, le=120)


class PauseSessionRequest(BaseSchema):
    reason: str = "user_initiated"


class VoiceSessionDTO(BaseSchema):
    id: int
    session_id: int
    user_id: str
    role_type: str
    skill_id: str
    difficulty: str
    custom_jd_text: str | None = None
    resume_id: int | None = None
    intro_enabled: bool
    tech_enabled: bool
    project_enabled: bool
    hr_enabled: bool
    llm_provider: str | None = None
    current_phase: str
    status: str
    planned_duration: int
    actual_duration: int | None = None
    start_time: NaiveIsoDatetime
    end_time: NaiveIsoDatetime | None = None
    created_at: NaiveIsoDatetime
    updated_at: NaiveIsoDatetime
    paused_at: NaiveIsoDatetime | None = None
    resumed_at: NaiveIsoDatetime | None = None
    evaluate_status: str | None = None
    web_socket_url: str | None = None


class VoiceSessionMetaDTO(BaseSchema):
    id: int
    session_id: int
    role_type: str
    skill_id: str
    status: str
    current_phase: str
    start_time: NaiveIsoDatetime
    end_time: NaiveIsoDatetime | None = None
    created_at: NaiveIsoDatetime
    updated_at: NaiveIsoDatetime
    actual_duration: int | None = None
    message_count: int = 0
    evaluate_status: str | None = None
    evaluate_error: str | None = None


class VoiceMessageDTO(BaseSchema):
    id: int
    session_id: int
    message_type: str
    phase: str
    user_recognized_text: str | None = None
    ai_generated_text: str | None = None
    timestamp: NaiveIsoDatetime
    sequence_num: int


class VoiceAnswerDetailDTO(BaseSchema):
    """语音评估扁平逐题项，对齐前端 `VoiceAnswerDetail`。"""

    question_index: int
    question: str
    category: str
    user_answer: str | None = None
    score: int
    feedback: str
    reference_answer: str | None = None
    key_points: list[str] = Field(default_factory=list)


class VoiceEvaluationDetailDTO(BaseSchema):
    session_id: int
    total_questions: int
    overall_score: int
    overall_feedback: str
    strengths: list[str]
    improvements: list[str]
    answers: list[VoiceAnswerDetailDTO]


class VoiceEvaluationStatusDTO(BaseSchema):
    evaluate_status: str
    evaluate_error: str | None = None
    evaluation: VoiceEvaluationDetailDTO | None = None
