from enum import Enum


class RagSessionStatus(Enum):
    """RAG 聊天会话状态：ACTIVE（活跃）-> ARCHIVED（归档）。"""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
