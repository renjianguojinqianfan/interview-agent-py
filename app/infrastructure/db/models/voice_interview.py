from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class VoiceInterviewSession(Base):
    """语音面试会话 ORM。对应 voice_interview_sessions 表。

    status 复用 VoiceSessionStatus（IN_PROGRESS/PAUSED/COMPLETED/FAILED）；
    current_phase 复用 InterviewPhase（INTRO/TECH/PROJECT/HR/COMPLETED）；
    evaluate_status 复用 AsyncTaskStatus（PENDING/PROCESSING/COMPLETED/FAILED）。
    """

    __tablename__ = "voice_interview_sessions"
    __table_args__ = ({"comment": "语音面试会话"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    role_type: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(64), nullable=False, default="java-backend")
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False, default="mid")
    custom_jd_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    intro_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tech_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    project_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hr_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    current_phase: Mapped[str] = mapped_column(String(20), nullable=False, default="INTRO")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="IN_PROGRESS")
    planned_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    actual_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluate_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    evaluate_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    messages: Mapped[list["VoiceInterviewMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="VoiceInterviewMessage.sequence_num",
    )
    evaluation: Mapped["VoiceInterviewEvaluation | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class VoiceInterviewMessage(Base):
    """语音面试消息 ORM。对应 voice_interview_messages 表。

    一行存一对 QA：ai_generated_text 为 AI 提问，user_recognized_text 为用户作答（ASR 转写）。
    用户作答回填到最近一条 ai_generated_text 非空且 user_recognized_text 为空的行
    （fillLatestUnansweredQuestion，#17 实现）。
    """

    __tablename__ = "voice_interview_messages"
    __table_args__ = ({"comment": "语音面试消息"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("voice_interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_type: Mapped[str] = mapped_column(String(20), nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    user_recognized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_generated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sequence_num: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session: Mapped[VoiceInterviewSession] = relationship(back_populates="messages")


class VoiceInterviewEvaluation(Base):
    """语音面试评估 ORM。对应 voice_interview_evaluations 表。

    与 VoiceInterviewSession 1:1（session_id 唯一）。评估结果由统一评估服务生成，
    逐题明细 / 优势 / 改进 / 参考答案以 JSON 文本存储，category_scores 读侧从逐题明细重建。
    """

    __tablename__ = "voice_interview_evaluations"
    __table_args__ = ({"comment": "语音面试评估"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("voice_interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_evaluations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    improvements_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_answers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    interviewer_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interview_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session: Mapped[VoiceInterviewSession] = relationship(back_populates="evaluation")
