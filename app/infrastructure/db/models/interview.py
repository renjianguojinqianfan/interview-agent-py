from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class InterviewSession(Base):
    """面试会话 ORM。对应 interview_sessions 表。

    evaluate_status / evaluate_error 为异步评估任务状态（#8 仅写入 PENDING/FAILED，#9 更新完整生命周期）。
    """

    __tablename__ = "interview_sessions"
    __table_args__ = ({"comment": "文字面试会话"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    skill_id: Mapped[str] = mapped_column(String(64), nullable=False, default="java-backend")
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False, default="mid")
    resume_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_question_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    questions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    improvements_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_answers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluate_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    evaluate_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    answers: Mapped[list["InterviewAnswer"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class InterviewAnswer(Base):
    """面试答案 ORM。对应 interview_answers 表。

    (session_id, question_index) 唯一约束：同一会话同一题只允许一条答案记录（upsert 语义）。
    """

    __tablename__ = "interview_answers"
    __table_args__ = (
        UniqueConstraint("session_id", "question_index", name="uk_interview_answer_session_question"),
        {"comment": "文字面试答案"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_index: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_points_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session: Mapped[InterviewSession] = relationship(back_populates="answers")
