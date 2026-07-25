"""知识库题库 DTO 与请求模型（对齐 Java Controller 与前端 knowledgebase.ts，issue #42）。"""

from typing import Literal

from app.api.responses import BaseSchema, NaiveIsoDatetime

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
