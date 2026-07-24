# ruff: noqa: N815  LLM 输出模型字段须 camelCase 对齐 prompt 的 Output Format
"""文字面试应用层 DTO 与 LLM 输出模型。"""

from pydantic import AliasChoices, BaseModel, Field

from app.api.responses import BaseSchema, NaiveIsoDatetime
from app.domain.entities.interview import MAX_QUESTION_COUNT, MIN_QUESTION_COUNT


class QuestionItem(BaseModel):
    """LLM 出题输出单项，字段对应 interview-question-*-system.st 的输出结构。"""

    question: str
    type: str
    category: str
    topicSummary: str | None = None
    followUps: list[str] = Field(default_factory=list)


class QuestionList(BaseModel):
    """LLM 出题输出模型。"""

    questions: list[QuestionItem]


class InterviewQuestionDTO(BaseSchema):
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


class SubmitAnswerRequest(BaseSchema):
    question_index: int = Field(ge=0)
    answer: str = Field(min_length=1)


class SubmitAnswerResponse(BaseSchema):
    has_next_question: bool
    next_question: InterviewQuestionDTO | None = None
    current_index: int
    total_questions: int


class InterviewSessionDTO(BaseSchema):
    session_id: str
    resume_text: str
    total_questions: int
    current_question_index: int
    questions: list[InterviewQuestionDTO]
    status: str


class SessionListItemDTO(BaseSchema):
    session_id: str
    skill_id: str
    difficulty: str
    resume_id: int | None = None
    total_questions: int
    status: str
    evaluate_status: str | None = None
    evaluate_error: str | None = None
    overall_score: int | None = None
    created_at: NaiveIsoDatetime
    completed_at: NaiveIsoDatetime | None = None


class CurrentQuestionResponse(BaseSchema):
    completed: bool
    message: str | None = None
    question: InterviewQuestionDTO | None = None


class CreateSessionRequest(BaseSchema):
    question_count: int = Field(ge=MIN_QUESTION_COUNT, le=MAX_QUESTION_COUNT)
    skill_id: str = Field(min_length=1)
    difficulty: str = "mid"
    resume_id: int | None = None
    resume_text: str | None = None
    force_create: bool = Field(
        default=False,
        validation_alias=AliasChoices("forceCreate", "forceNew", "force_create", "force_new"),
    )
    llm_provider: str | None = None
    custom_categories: list[dict[str, object]] = Field(default_factory=list)
    jd_text: str | None = None


class CategoryScoreDTO(BaseSchema):
    category: str
    score: int
    question_count: int


class QuestionEvaluationDetailDTO(BaseSchema):
    question_index: int
    question: str
    category: str
    user_answer: str | None = None
    score: int
    feedback: str


class ReferenceAnswerDTO(BaseSchema):
    question_index: int
    question: str
    reference_answer: str
    key_points: list[str] = Field(default_factory=list)


class EvaluationResultDTO(BaseSchema):
    session_id: str
    total_questions: int
    overall_score: int
    overall_feedback: str
    category_scores: list[CategoryScoreDTO]
    question_details: list[QuestionEvaluationDetailDTO]
    strengths: list[str]
    improvements: list[str]
    reference_answers: list[ReferenceAnswerDTO]
    evaluate_status: str


class AnswerItemDTO(BaseSchema):
    """面试详情逐题项，对齐前端 historyApi `AnswerItem`（userAnswer 为非空 string）。"""

    question_index: int
    question: str
    category: str
    user_answer: str = ""
    score: int
    feedback: str
    reference_answer: str | None = None
    key_points: list[str] = Field(default_factory=list)
    answered_at: NaiveIsoDatetime


class InterviewDetailDTO(BaseSchema):
    """文字面试详情，对齐前端 historyApi `InterviewDetail`（InterviewItem + answers[]）。"""

    id: int
    session_id: str
    total_questions: int
    status: str
    evaluate_status: str | None = None
    evaluate_error: str | None = None
    overall_score: int | None = None
    overall_feedback: str | None = None
    created_at: NaiveIsoDatetime
    completed_at: NaiveIsoDatetime | None = None
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    reference_answers: list[ReferenceAnswerDTO] = Field(default_factory=list)
    answers: list[AnswerItemDTO] = Field(default_factory=list)
