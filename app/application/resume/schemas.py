from datetime import datetime

from app.api.responses import BaseSchema


class ResumeInfoDTO(BaseSchema):
    id: int
    filename: str
    analyze_status: str


class StorageInfoDTO(BaseSchema):
    file_key: str
    file_url: str
    resume_id: int


class ResumeUploadResponse(BaseSchema):
    resume: ResumeInfoDTO
    storage: StorageInfoDTO
    duplicate: bool


class ResumeListItemDTO(BaseSchema):
    id: int
    filename: str
    file_size: int | None
    uploaded_at: datetime
    access_count: int
    latest_score: int | None
    last_analyzed_at: datetime | None
    interview_count: int
    analyze_status: str
    analyze_error: str | None


class ResumePageDTO(BaseSchema):
    items: list[ResumeListItemDTO]
    total: int
    page: int
    size: int


class AnalysisHistoryDTO(BaseSchema):
    id: int
    overall_score: int | None
    content_score: int | None
    structure_score: int | None
    skill_match_score: int | None
    expression_score: int | None
    project_score: int | None
    summary: str | None
    analyzed_at: datetime
    strengths: list[str]
    suggestions: list[dict[str, object]]


class ResumeDetailDTO(BaseSchema):
    id: int
    filename: str
    file_size: int | None
    content_type: str | None
    storage_url: str | None
    uploaded_at: datetime
    access_count: int
    resume_text: str | None
    analyze_status: str
    analyze_error: str | None
    analyses: list[AnalysisHistoryDTO]
