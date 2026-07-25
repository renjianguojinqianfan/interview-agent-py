from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vector_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    vector_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vector_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 题目异步生成状态机（migration 012）：NONE/QUEUED/PROCESSING/COMPLETED/FAILED + 恢复快照
    question_gen_status: Mapped[str] = mapped_column(String(20), nullable=False, default="NONE")
    question_gen_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    question_gen_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    question_gen_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_gen_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    question_gen_saved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_gen_skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_gen_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vectorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeBaseQuestion(Base):
    """知识库题库 ORM。对应 knowledge_base_questions 表（migration 012）。

    AI 生成或手动维护的面试题：题干 + 方向（category）+ 难度 + 参考答案 + 评分要点
    （key_points_json）+ 评分规则（scoring_rubric）+ 追问池（follow_ups_json）。
    skill_id 固定 knowledge-base 以复用既有会话表的非空约束。
    status DRAFT/ACTIVE 参与组卷（ARCHIVED/STALE 保留 Java 枚举全集）。
    """

    __tablename__ = "knowledge_base_questions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'ARCHIVED', 'STALE')",
            name="knowledge_base_questions_status_check",
        ),
        Index("idx_kb_question_kb_status", "knowledge_base_id", "status"),
        Index("idx_kb_question_skill_difficulty", "skill_id", "difficulty"),
        {"comment": "知识库面试题库"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_id: Mapped[str] = mapped_column(String(64), nullable=False, default="knowledge-base")
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    topic_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_points_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scoring_rubric: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_ups_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    kb_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
