from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.ai.provider_snapshot import ProviderSnapshot, looks_like_chat_model


def create_embeddings(config: ProviderSnapshot) -> OpenAIEmbeddings:
    if not config.supports_embedding or not config.embedding_model:
        raise BusinessException(
            ErrorCode.PROVIDER_CONFIG_READ_FAILED,
            f"Provider '{config.id}' 未配置可用的 Embedding 模型，无法执行知识库向量化",
        )
    if looks_like_chat_model(config.embedding_model):
        raise BusinessException(
            ErrorCode.PROVIDER_CONFIG_READ_FAILED,
            f"Provider '{config.id}' 的 Embedding Model 配成了聊天模型 "
            f"'{config.embedding_model}'，请填写该厂商真实的 Embedding 模型名",
        )
    return OpenAIEmbeddings(
        model=config.embedding_model,
        api_key=SecretStr(config.api_key) if config.api_key else None,
        base_url=config.base_url,
        dimensions=config.embedding_dimensions,
    )
