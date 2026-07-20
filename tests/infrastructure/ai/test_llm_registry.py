import base64
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_openai import ChatOpenAI

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.ai.encryption import ApiKeyEncryptionService
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.provider_snapshot import ProviderSnapshot, looks_like_chat_model
from app.infrastructure.db.models.llm_global_setting import LlmGlobalSetting
from app.infrastructure.db.models.llm_provider import LlmProvider

_ENCRYPTION_KEY = base64.b64encode(b"a" * 32).decode()


def _make_provider(
    provider_id: int = 1,
    provider_name: str = "dashscope",
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key: str = "",
    model: str = "qwen3.5-flash",
    embedding_model: str | None = "text-embedding-v3",
    embedding_dimensions: int = 1024,
    supports_embedding: bool = True,
    is_default: bool = True,
    temperature: float | None = 0.2,
) -> LlmProvider:
    return LlmProvider(
        id=provider_id,
        provider_name=provider_name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        supports_embedding=supports_embedding,
        is_default=is_default,
        temperature=temperature,
    )


def _make_global_setting(
    default_chat_provider_id: int = 1,
    default_embedding_provider_id: int | None = 1,
) -> LlmGlobalSetting:
    return LlmGlobalSetting(
        id=LlmGlobalSetting.SINGLETON_ID,
        default_chat_provider_id=default_chat_provider_id,
        default_embedding_provider_id=default_embedding_provider_id,
    )


def _make_mock_session_factory(
    by_id: dict[int, LlmProvider] | None = None,
    default_provider: LlmProvider | None = None,
    global_setting: LlmGlobalSetting | None = None,
):
    by_id = by_id or {}
    default_provider = default_provider or _make_provider()
    if global_setting is None:
        global_setting = _make_global_setting()

    @asynccontextmanager
    async def factory():
        session = AsyncMock()

        async def fake_execute(stmt):
            result = MagicMock()
            stmt_str = str(stmt)
            if "llm_global_setting" in stmt_str:
                result.scalar_one_or_none.return_value = global_setting
            else:
                scalar_result = MagicMock()
                scalar_result.first.return_value = by_id.get(1, default_provider)
                result.scalars.return_value = scalar_result
            return result

        session.execute = fake_execute
        yield session

    return factory


@pytest.fixture()
def encryption_service() -> ApiKeyEncryptionService:
    return ApiKeyEncryptionService(_ENCRYPTION_KEY)


@pytest.fixture()
def provider(encryption_service: ApiKeyEncryptionService) -> LlmProvider:
    return _make_provider(api_key=encryption_service.encrypt("sk-test-api-key"))


@pytest.fixture()
def registry(encryption_service: ApiKeyEncryptionService, provider: LlmProvider) -> LlmProviderRegistry:
    session_factory = _make_mock_session_factory(default_provider=provider)
    return LlmProviderRegistry(encryption_service, session_factory)


class TestLlmProviderRegistryGetChatClient:
    async def test_get_chat_client_returns_chat_openai(self, registry: LlmProviderRegistry) -> None:
        client = await registry.get_chat_client()
        assert isinstance(client, ChatOpenAI)

    async def test_get_chat_client_uses_provider_model(self, registry: LlmProviderRegistry) -> None:
        client = await registry.get_chat_client()
        assert client.model_name == "qwen3.5-flash"

    async def test_get_chat_client_uses_provider_base_url(self, registry: LlmProviderRegistry) -> None:
        client = await registry.get_chat_client()
        assert "dashscope" in client.openai_api_base

    async def test_get_chat_client_caches(self, registry: LlmProviderRegistry) -> None:
        client1 = await registry.get_chat_client()
        client2 = await registry.get_chat_client()
        assert client1 is client2

    async def test_get_chat_client_by_id(self, registry: LlmProviderRegistry) -> None:
        client = await registry.get_chat_client(provider_id=1)
        assert isinstance(client, ChatOpenAI)


class TestLlmProviderRegistryClientTypes:
    async def test_plain_client_cached_separately(self, registry: LlmProviderRegistry) -> None:
        default_client = await registry.get_chat_client()
        plain_client = await registry.get_plain_chat_client()
        assert default_client is not plain_client

    async def test_voice_client_cached_separately(self, registry: LlmProviderRegistry) -> None:
        default_client = await registry.get_chat_client()
        voice_client = await registry.get_voice_chat_client()
        assert default_client is not voice_client

    async def test_plain_client_caches(self, registry: LlmProviderRegistry) -> None:
        c1 = await registry.get_plain_chat_client()
        c2 = await registry.get_plain_chat_client()
        assert c1 is c2

    async def test_voice_client_has_streaming(self, registry: LlmProviderRegistry) -> None:
        voice_client = await registry.get_voice_chat_client()
        assert voice_client.streaming is True


class TestLlmProviderRegistryReload:
    async def test_reload_clears_cache(self, registry: LlmProviderRegistry) -> None:
        client1 = await registry.get_chat_client()
        registry.reload()
        client2 = await registry.get_chat_client()
        assert client1 is not client2


class TestLlmProviderRegistryProviderNotFound:
    async def test_provider_not_found_raises(self, encryption_service: ApiKeyEncryptionService) -> None:
        @asynccontextmanager
        async def empty_factory():
            session = AsyncMock()

            async def fake_execute(stmt):
                result = MagicMock()
                stmt_str = str(stmt)
                if "llm_global_setting" in stmt_str:
                    result.scalar_one_or_none.return_value = None
                else:
                    scalar_result = MagicMock()
                    scalar_result.first.return_value = None
                    result.scalars.return_value = scalar_result
                return result

            session.execute = fake_execute
            yield session

        registry = LlmProviderRegistry(encryption_service, empty_factory)
        with pytest.raises(BusinessException) as exc_info:
            await registry.get_chat_client(provider_id=999)
        assert exc_info.value.error_code == ErrorCode.PROVIDER_NOT_FOUND


class TestLlmProviderRegistryTemperatureDefault:
    async def test_default_temperature_when_null(self, encryption_service: ApiKeyEncryptionService) -> None:
        provider = _make_provider(
            api_key=encryption_service.encrypt("sk-test"),
            temperature=None,
        )
        session_factory = _make_mock_session_factory(default_provider=provider)
        registry = LlmProviderRegistry(encryption_service, session_factory)
        client = await registry.get_chat_client()
        assert client.temperature == 0.2


class TestProviderSnapshot:
    def test_provider_snapshot_fields(self) -> None:
        snapshot = ProviderSnapshot(
            id=1,
            base_url="https://example.com",
            api_key="sk-test",
            model="gpt-4",
            embedding_model="text-embedding-3",
            embedding_dimensions=1024,
            supports_embedding=True,
            temperature=0.5,
        )
        assert snapshot.id == 1
        assert snapshot.model == "gpt-4"
        assert snapshot.supports_embedding is True


class TestLooksLikeChatModel:
    def test_qwen_model_detected_as_chat(self) -> None:
        assert looks_like_chat_model("qwen-plus") is True

    def test_glm_model_detected_as_chat(self) -> None:
        assert looks_like_chat_model("glm-4") is True

    def test_deepseek_model_detected_as_chat(self) -> None:
        assert looks_like_chat_model("deepseek-chat") is True

    def test_embedding_model_not_detected_as_chat(self) -> None:
        assert looks_like_chat_model("text-embedding-v3") is False

    def test_case_insensitive(self) -> None:
        assert looks_like_chat_model("Qwen-Plus") is True
