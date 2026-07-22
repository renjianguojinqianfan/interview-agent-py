from app.api.responses import BaseSchema, NaiveIsoDatetime


class KnowledgeBaseInfoDTO(BaseSchema):
    id: int
    filename: str
    vector_status: str


class StorageInfoDTO(BaseSchema):
    file_key: str
    file_url: str
    knowledge_base_id: int


class KnowledgeBaseUploadResponse(BaseSchema):
    knowledge_base: KnowledgeBaseInfoDTO
    storage: StorageInfoDTO
    duplicate: bool


class KnowledgeBaseListItemDTO(BaseSchema):
    id: int
    name: str
    category: str | None = None
    original_filename: str
    file_size: int | None = None
    content_type: str | None = None
    uploaded_at: NaiveIsoDatetime
    last_accessed_at: NaiveIsoDatetime
    access_count: int
    question_count: int
    vector_status: str
    vector_error: str | None = None
    chunk_count: int


class KnowledgeBaseStatsDTO(BaseSchema):
    total_count: int
    total_question_count: int
    total_access_count: int
    completed_count: int
    processing_count: int


class UpdateCategoryRequest(BaseSchema):
    category: str | None = None
