import base64
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_openai import OpenAIEmbeddings

from app.api.errors import BusinessException, ErrorCode
from app.infrastructure.ai.embeddings import create_embeddings
from app.infrastructure.ai.encryption import ApiKeyEncryptionService
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.provider_snapshot import ProviderSnapshot
from app.infrastructure.db.models.llm_provider import LlmProvider

_ENCRYPTION_KEY = base64.b64encode(b"a" * 32).decode()


def _make_snapshot(
    api_key: str = "sk-test",
    embedding_model: str | None = "text-embedding-v3",
    embedding_dimensions: int = 1024,
    supports_embedding: bool = True,
) -> ProviderSnapshot:
    return ProviderSnapshot(
        id=1,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=api_key,
        model="qwen3.5-flash",
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        supports_embedding=supports_embedding,
        temperature=0.2,
    )


def _make_provider(encryption_service: ApiKeyEncryptionService) -> LlmProvider:
    return LlmProvider(
        id=1,
        provider_name="dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=encryption_service.encrypt("sk-test"),
        model="qwen3.5-flash",
        embedding_model="text-embedding-v3",
        embedding_dimensions=1024,
        supports_embedding=True,
        is_default=True,
        temperature=0.2,
    )


def _make_mock_session_factory(provider: LlmProvider):
    @asynccontextmanager
    async def factory():
        session = AsyncMock()

        async def fake_execute(stmt):
            result = MagicMock()
            scalar_result = MagicMock()
            scalar_result.first.return_value = provider
            result.scalars.return_value = scalar_result
            return result

        session.execute = fake_execute
        yield session

    return factory


class TestCreateEmbeddings:
    def test_returns_openai_embeddings(self) -> None:
        config = _make_snapshot()
        embeddings = create_embeddings(config)
        assert isinstance(embeddings, OpenAIEmbeddings)

    def test_uses_embedding_model_name(self) -> None:
        config = _make_snapshot(embedding_model="text-embedding-v3")
        embeddings = create_embeddings(config)
        assert embeddings.model == "text-embedding-v3"

    def test_uses_1024_dimensions(self) -> None:
        config = _make_snapshot(embedding_dimensions=1024)
        embeddings = create_embeddings(config)
        assert embeddings.dimensions == 1024

    def test_uses_provider_base_url(self) -> None:
        config = _make_snapshot()
        embeddings = create_embeddings(config)
        assert "dashscope" in embeddings.openai_api_base

    def test_raises_when_no_embedding_support(self) -> None:
        config = _make_snapshot(supports_embedding=False, embedding_model=None)
        with pytest.raises(BusinessException) as exc_info:
            create_embeddings(config)
        assert exc_info.value.error_code == ErrorCode.PROVIDER_CONFIG_READ_FAILED

    def test_raises_when_embedding_model_is_chat_model(self) -> None:
        config = _make_snapshot(embedding_model="qwen-plus")
        with pytest.raises(BusinessException) as exc_info:
            create_embeddings(config)
        assert exc_info.value.error_code == ErrorCode.PROVIDER_CONFIG_READ_FAILED
        assert "聊天模型" in exc_info.value.message or "Embedding" in exc_info.value.message

    def test_raises_when_embedding_model_blank_but_supported(self) -> None:
        config = _make_snapshot(embedding_model=None, supports_embedding=True)
        with pytest.raises(BusinessException):
            create_embeddings(config)


class TestLlmProviderRegistryGetEmbeddings:
    async def test_get_embeddings_returns_openai_embeddings(
        self,
    ) -> None:
        encryption_service = ApiKeyEncryptionService(_ENCRYPTION_KEY)
        provider = _make_provider(encryption_service)
        session_factory = _make_mock_session_factory(provider)
        registry = LlmProviderRegistry(encryption_service, session_factory)

        embeddings = await registry.get_embeddings()
        assert isinstance(embeddings, OpenAIEmbeddings)

    async def test_get_embeddings_caches(
        self,
    ) -> None:
        encryption_service = ApiKeyEncryptionService(_ENCRYPTION_KEY)
        provider = _make_provider(encryption_service)
        session_factory = _make_mock_session_factory(provider)
        registry = LlmProviderRegistry(encryption_service, session_factory)

        e1 = await registry.get_embeddings()
        e2 = await registry.get_embeddings()
        assert e1 is e2

    async def test_reload_clears_embeddings_cache(
        self,
    ) -> None:
        encryption_service = ApiKeyEncryptionService(_ENCRYPTION_KEY)
        provider = _make_provider(encryption_service)
        session_factory = _make_mock_session_factory(provider)
        registry = LlmProviderRegistry(encryption_service, session_factory)

        e1 = await registry.get_embeddings()
        registry.reload()
        e2 = await registry.get_embeddings()
        assert e1 is not e2
