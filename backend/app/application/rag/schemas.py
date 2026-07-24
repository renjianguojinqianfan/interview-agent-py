from app.api.responses import BaseSchema, NaiveIsoDatetime
from app.application.knowledgebase.schemas import KnowledgeBaseListItemDTO


class CreateRagSessionRequest(BaseSchema):
    knowledge_base_ids: list[int]
    title: str | None = None


class SendMessageRequest(BaseSchema):
    question: str


class UpdateTitleRequest(BaseSchema):
    title: str


class RagSessionDTO(BaseSchema):
    """创建会话响应（对齐 Java RagChatDTO.SessionDTO）。"""

    id: int
    title: str | None
    knowledge_base_ids: list[int]
    created_at: NaiveIsoDatetime


class RagSessionListItemDTO(BaseSchema):
    """会话列表项（对齐 Java RagChatDTO.SessionListItemDTO）。"""

    id: int
    title: str | None
    message_count: int
    knowledge_base_names: list[str]
    updated_at: NaiveIsoDatetime
    is_pinned: bool


class RagMessageDTO(BaseSchema):
    """消息项：type 为 'user' | 'assistant'（对齐 Java RagChatDTO.MessageDTO）。"""

    id: int
    type: str
    content: str | None
    created_at: NaiveIsoDatetime


class RagSessionDetailDTO(BaseSchema):
    """会话详情（对齐 Java RagChatDTO.SessionDetailDTO）。"""

    id: int
    title: str | None
    knowledge_bases: list[KnowledgeBaseListItemDTO]
    messages: list[RagMessageDTO]
    created_at: NaiveIsoDatetime
    updated_at: NaiveIsoDatetime


class RagSourceDTO(BaseSchema):
    content: str
    score: float
    kb_id: int
