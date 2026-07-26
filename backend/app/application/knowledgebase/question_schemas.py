"""知识库题库 DTO 与请求模型（对齐 Java Controller 与前端 knowledgebase.ts，issue #42）。"""

from typing import Literal

from pydantic import Field

from app.api.responses import BaseSchema, NaiveIsoDatetime
from app.domain.entities.interview import MAX_QUESTION_COUNT
from app.domain.services.question_bank import MAX_FOLLOW_UP_COUNT

KnowledgeBaseQuestionStatusLiteral = Literal["DRAFT", "ACTIVE", "ARCHIVED", "STALE"]


class KnowledgeBaseQuestionFollowUpDTO(BaseSchema):
    question: str
    reference_answer: str | None = None
    key_points: list[str] = []
    scoring_rubric: str | None = None


class KnowledgeBaseQuestionDTO(BaseSchema):
    id: int
    knowledge_base_id: int
    knowledge_base_name: str | None = None
    skill_id: str
    difficulty: str | None = None
    type: str | None = None
    category: str | None = None
    question: str
    topic_summary: str | None = None
    reference_answer: str | None = None
    key_points: list[str] = []
    scoring_rubric: str | None = None
    follow_ups: list[KnowledgeBaseQuestionFollowUpDTO] = []
    source_context: str | None = None
    status: str
    created_at: NaiveIsoDatetime
    updated_at: NaiveIsoDatetime


class CreateKnowledgeBaseQuestionRequest(BaseSchema):
    difficulty: str | None = None
    type: str | None = None
    category: str
    question: str
    topic_summary: str | None = None
    reference_answer: str | None = None
    key_points: list[str] | None = None
    scoring_rubric: str | None = None
    follow_ups: list[KnowledgeBaseQuestionFollowUpDTO] | None = None
    source_context: str | None = None
    status: KnowledgeBaseQuestionStatusLiteral | None = None


class UpdateKnowledgeBaseQuestionRequest(BaseSchema):
    """部分更新：None 表示未提供、跳过该字段（对齐 Java record 空字段语义）。"""

    difficulty: str | None = None
    type: str | None = None
    category: str | None = None
    question: str | None = None
    topic_summary: str | None = None
    reference_answer: str | None = None
    key_points: list[str] | None = None
    scoring_rubric: str | None = None
    follow_ups: list[KnowledgeBaseQuestionFollowUpDTO] | None = None
    source_context: str | None = None
    status: KnowledgeBaseQuestionStatusLiteral | None = None


class UpdateKnowledgeBaseQuestionStatusRequest(BaseSchema):
    status: KnowledgeBaseQuestionStatusLiteral


class CategoryCountDTO(BaseSchema):
    category: str
    count: int


class GenerateKnowledgeBaseQuestionsRequest(BaseSchema):
    """题库生成提交请求（校验对齐 Java GenerateKnowledgeBaseQuestionsRequest）。"""

    difficulty: Literal["junior", "mid", "senior"] | None = None
    question_count: int = Field(ge=1, le=30)
    follow_up_count: int | None = Field(default=None, ge=0, le=5)
    category_limit: int = Field(ge=1, le=5)
    llm_provider: str | None = Field(default=None, max_length=64)


class QuestionGenerationConfigDTO(BaseSchema):
    """生成任务配置快照（存于 knowledge_bases.question_gen_config，camelCase JSON）。"""

    difficulty: str
    question_count: int
    follow_up_count: int
    category_limit: int
    llm_provider: str | None = None


class QuestionGenStatusResponse(BaseSchema):
    knowledge_base_id: int
    question_gen_status: str
    question_gen_task_id: str | None = None
    question_gen_config: QuestionGenerationConfigDTO | None = None
    saved_count: int = 0
    skipped_count: int = 0
    message: str | None = None
    error: str | None = None
    updated_at: NaiveIsoDatetime | None = None


class CreateKnowledgeBaseInterviewRequest(BaseSchema):
    """组卷面试创建请求（校验对齐 Java CreateKnowledgeBaseInterviewRequest，issue #44）。"""

    knowledge_base_id: int
    # 面试方向可空：空表示覆盖知识库内所有方向的已启用题目
    category: str | None = None
    difficulty: str | None = None
    main_question_count: int = Field(ge=1, le=MAX_QUESTION_COUNT)
    follow_up_count: int = Field(ge=0, le=MAX_FOLLOW_UP_COUNT)
    llm_provider: str | None = Field(default=None, max_length=64)


class InterviewCategoryOptionDTO(BaseSchema):
    category: str
    available_question_count: int


class InterviewFollowUpOptionDTO(BaseSchema):
    follow_up_count: int
    available_question_count: int
    selectable: bool


class KnowledgeBaseInterviewCapacityResponse(BaseSchema):
    """容量预检：指定方向/难度/主问题数下的可用容量矩阵（对齐 Java 同名 response）。"""

    knowledge_base_id: int
    category: str | None = None
    difficulty: str
    main_question_count: int
    categories: list[InterviewCategoryOptionDTO]
    follow_up_options: list[InterviewFollowUpOptionDTO]
