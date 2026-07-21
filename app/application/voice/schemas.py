"""语音面试应用层 Pydantic schemas。

复用文字面试的评估相关 DTO（CategoryScoreDTO/QuestionEvaluationDetailDTO/ReferenceAnswerDTO），
因 EvaluationReport 为文字/语音共用领域实体。
"""

from pydantic import Field

from app.api.responses import BaseSchema, NaiveIsoDatetime
from app.application.interview.schemas import (
    CategoryScoreDTO,
    QuestionEvaluationDetailDTO,
    ReferenceAnswerDTO,
)
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
    llm_provider_id: int | None = None
    planned_duration: int = Field(default=DEFAULT_PLANNED_DURATION_MINUTES, ge=1, le=120)


class PauseSessionRequest(BaseSchema):
    reason: str = "user_initiated"


class VoiceSessionDTO(BaseSchema):
    id: int
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


class VoiceSessionMetaDTO(BaseSchema):
    id: int
    role_type: str
    skill_id: str
    status: str
    current_phase: str
    start_time: NaiveIsoDatetime
    end_time: NaiveIsoDatetime | None = None
    evaluate_status: str | None = None
    updated_at: NaiveIsoDatetime


class VoiceMessageDTO(BaseSchema):
    id: int
    session_id: int
    message_type: str
    phase: str
    user_recognized_text: str | None = None
    ai_generated_text: str | None = None
    timestamp: NaiveIsoDatetime
    sequence_num: int


class VoiceEvaluationDetailDTO(BaseSchema):
    overall_score: int
    overall_feedback: str
    category_scores: list[CategoryScoreDTO]
    question_details: list[QuestionEvaluationDetailDTO]
    strengths: list[str]
    improvements: list[str]
    reference_answers: list[ReferenceAnswerDTO]


class VoiceEvaluationStatusDTO(BaseSchema):
    evaluate_status: str
    evaluation: VoiceEvaluationDetailDTO | None = None
