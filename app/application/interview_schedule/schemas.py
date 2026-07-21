from datetime import datetime

from app.api.responses import BaseSchema


class CreateScheduleRequest(BaseSchema):
    company_name: str
    position: str
    interview_time: datetime
    interview_type: str | None = None
    meeting_link: str | None = None
    round_number: int = 1
    interviewer: str | None = None
    notes: str | None = None


class InterviewScheduleDTO(BaseSchema):
    id: int
    company_name: str
    position: str
    interview_time: datetime
    interview_type: str | None = None
    meeting_link: str | None = None
    round_number: int = 1
    interviewer: str | None = None
    notes: str | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ParseRequest(BaseSchema):
    raw_text: str
    source: str | None = None


class ParsedScheduleData(BaseSchema):
    """LLM 结构化输出模型，字段名 camelCase 对齐 prompt 的 Output Format。"""

    company_name: str
    position: str
    interview_time: str
    interview_type: str | None = None
    meeting_link: str | None = None
    round_number: int = 1
    interviewer: str | None = None
    notes: str | None = None


class ParseResponse(BaseSchema):
    success: bool
    data: CreateScheduleRequest | None = None
    confidence: float = 0.0
    parse_method: str = "none"
    log: str = ""
