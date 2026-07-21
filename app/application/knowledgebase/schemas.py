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
    filename: str
    file_size: int | None
    uploaded_at: NaiveIsoDatetime
    chunk_count: int
    vector_status: str
    vector_error: str | None
    vectorized_at: NaiveIsoDatetime | None


class KnowledgeBasePageDTO(BaseSchema):
    items: list[KnowledgeBaseListItemDTO]
    total: int
    page: int
    size: int


class KnowledgeBaseDetailDTO(BaseSchema):
    id: int
    filename: str
    file_size: int | None
    content_type: str | None
    storage_url: str | None
    uploaded_at: NaiveIsoDatetime
    content_text: str | None
    chunk_count: int
    vector_status: str
    vector_error: str | None
    vectorized_at: NaiveIsoDatetime | None
