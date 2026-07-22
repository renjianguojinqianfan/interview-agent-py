from app.api.responses import BaseSchema, NaiveIsoDatetime


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
    uploaded_at: NaiveIsoDatetime
    access_count: int
    latest_score: int | None
    last_analyzed_at: NaiveIsoDatetime | None
    interview_count: int
    analyze_status: str
    analyze_error: str | None


class ResumeStatsDTO(BaseSchema):
    total_count: int
    total_interview_count: int
    total_access_count: int


class InterviewHistoryItemDTO(BaseSchema):
    """简历详情页展示的关联面试记录项（对齐 Java InterviewHistoryItemDTO）。"""

    id: int
    session_id: str
    total_questions: int
    status: str
    evaluate_status: str | None = None
    evaluate_error: str | None = None
    overall_score: int | None = None
    created_at: NaiveIsoDatetime
    completed_at: NaiveIsoDatetime | None = None


class AnalysisHistoryDTO(BaseSchema):
    id: int
    overall_score: int | None
    content_score: int | None
    structure_score: int | None
    skill_match_score: int | None
    expression_score: int | None
    project_score: int | None
    summary: str | None
    analyzed_at: NaiveIsoDatetime
    strengths: list[str]
    suggestions: list[dict[str, object]]


class ResumeDetailDTO(BaseSchema):
    id: int
    filename: str
    file_size: int | None
    content_type: str | None
    storage_url: str | None
    uploaded_at: NaiveIsoDatetime
    access_count: int
    resume_text: str | None
    analyze_status: str
    analyze_error: str | None
    analyses: list[AnalysisHistoryDTO]
    interviews: list[InterviewHistoryItemDTO]
