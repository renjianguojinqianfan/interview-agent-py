from app.api.responses import BaseSchema, NaiveIsoDatetime


class CreateRagSessionRequest(BaseSchema):
    knowledge_base_ids: list[int]
    title: str | None = None


class RagQueryRequest(BaseSchema):
    question: str


class RagSessionInfoDTO(BaseSchema):
    id: int
    session_id: str
    title: str | None
    status: str
    pinned: bool
    knowledge_base_ids: list[int]
    created_at: NaiveIsoDatetime
    updated_at: NaiveIsoDatetime


class RagSessionPageDTO(BaseSchema):
    items: list[RagSessionInfoDTO]
    total: int
    page: int
    size: int


class RagSourceDTO(BaseSchema):
    content: str
    score: float
    kb_id: int


class RagMessageDTO(BaseSchema):
    id: int
    role: str
    content: str | None
    sources: list[RagSourceDTO]
    created_at: NaiveIsoDatetime


class RagSessionDetailDTO(BaseSchema):
    id: int
    session_id: str
    title: str | None
    status: str
    pinned: bool
    knowledge_base_ids: list[int]
    created_at: NaiveIsoDatetime
    updated_at: NaiveIsoDatetime
    messages: list[RagMessageDTO]


class RagAnswerDTO(BaseSchema):
    answer: str
    sources: list[RagSourceDTO]
    no_result: bool
