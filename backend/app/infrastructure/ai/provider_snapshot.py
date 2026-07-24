from dataclasses import dataclass


@dataclass
class ProviderSnapshot:
    id: int
    base_url: str
    api_key: str
    model: str
    embedding_model: str | None
    embedding_dimensions: int
    supports_embedding: bool
    temperature: float | None


_CHAT_MODEL_PREFIXES = (
    "glm-",
    "deepseek",
    "kimi",
    "moonshot",
    "qwen",
    "ernie",
)


def looks_like_chat_model(model: str) -> bool:
    """规格外增强：防止用户将聊天模型名误填到 embedding_model 字段。"""
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in _CHAT_MODEL_PREFIXES)
