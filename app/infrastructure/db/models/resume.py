from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyze_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    analyze_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    analyses: Mapped[list["ResumeAnalysis"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ResumeAnalysis(Base):
    __tablename__ = "resume_analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
    )
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structure_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skill_match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expression_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    resume: Mapped[Resume] = relationship(back_populates="analyses")
