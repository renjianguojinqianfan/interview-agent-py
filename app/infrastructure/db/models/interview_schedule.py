from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class InterviewSchedule(Base):
    """面试日程 ORM。对应 interview_schedule 表。

    记录 Interviewee 的真实面试日程（非模拟面试）。
    """

    __tablename__ = "interview_schedule"
    __table_args__ = ({"comment": "面试日程"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[str] = mapped_column(String(200), nullable=False)
    interview_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    interview_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    meeting_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    interviewer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
