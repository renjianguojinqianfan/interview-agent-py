import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.llm_provider.schemas import (
    AsrConfigRequest,
    CreateProviderRequest,
    DefaultProviderDTO,
    TtsConfigRequest,
    UpdateProviderRequest,
)
from app.application.llm_provider.service import LlmProviderService, _mask_api_key
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.ai.encryption import ApiKeyEncryptionService
from app.infrastructure.db.models.llm_global_setting import LlmGlobalSetting
from app.infrastructure.db.models.llm_provider import LlmProvider
from app.infrastructure.db.models.voice_config import VoiceConfig

_ENCRYPTION_KEY = base64.b64encode(b"a" * 32).decode()


def _make_provider(
    provider_id: int = 1,
    provider_name: str = "dashscope",
    api_key_cipher: str = "",
    supports_embedding: bool = True,
    is_default: bool = True,
) -> LlmProvider:
    return LlmProvider(
        id=provider_id,
        provider_name=provider_name,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=api_key_cipher,
        model="qwen3.5-flash",
        embedding_model="text-embedding-v3",
        embedding_dimensions=1024,
        supports_embedding=supports_embedding,
        is_default=is_default,
        temperature=0.2,
    )


def _make_global_setting(chat_id: int = 1, emb_id: int | None = 1) -> LlmGlobalSetting:
    return LlmGlobalSetting(
        id=LlmGlobalSetting.SINGLETON_ID,
        default_chat_provider_id=chat_id,
        default_embedding_provider_id=emb_id,
    )


def _make_voice_config(asr_key_cipher: str = "", tts_key_cipher: str = "") -> VoiceConfig:
    return VoiceConfig(
        id=VoiceConfig.SINGLETON_ID,
        asr_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        asr_model="qwen3-asr-flash-realtime",
        asr_api_key=asr_key_cipher,
        asr_language="zh",
        asr_format="pcm",
        asr_sample_rate=16000,
        asr_enable_turn_detection=True,
        asr_turn_detection_type="server_vad",
        asr_turn_detection_threshold=0.0,
        asr_turn_detection_silence_duration_ms=2000,
        tts_model="qwen3-tts-flash-realtime",
        tts_api_key=tts_key_cipher,
        tts_voice="Cherry",
        tts_format="pcm",
        tts_sample_rate=24000,
        tts_mode="commit",
        tts_language_type="Chinese",
        tts_speech_rate=1.0,
        tts_volume=60,
    )


@pytest.fixture()
def encryption_service() -> ApiKeyEncryptionService:
    return ApiKeyEncryptionService(_ENCRYPTION_KEY)


@pytest.fixture()
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture()
def mock_provider_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save = AsyncMock(side_effect=lambda session, p: p)
    return repo


@pytest.fixture()
def mock_global_setting_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save = AsyncMock(side_effect=lambda session, s: s)
    return repo


@pytest.fixture()
def mock_voice_config_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def mock_registry() -> MagicMock:
    registry = MagicMock()
    registry.reload = MagicMock()
    return registry


@pytest.fixture()
def service(
    mock_session: AsyncMock,
    mock_provider_repo: AsyncMock,
    mock_global_setting_repo: AsyncMock,
    mock_voice_config_repo: AsyncMock,
    encryption_service: ApiKeyEncryptionService,
    mock_registry: MagicMock,
) -> LlmProviderService:
    return LlmProviderService(
        session=mock_session,
        provider_repository=mock_provider_repo,
        global_setting_repository=mock_global_setting_repo,
        voice_config_repository=mock_voice_config_repo,
        encryption_service=encryption_service,
        registry=mock_registry,
    )


class TestMaskApiKey:
    def test_empty_key(self) -> None:
        assert _mask_api_key("") == ""

    def test_short_key(self) -> None:
        assert _mask_api_key("abc") == "***"

    def test_long_key(self) -> None:
        assert _mask_api_key("sk-abcdef123456") == "sk-***456"


class TestCreateProvider:
    async def test_create_provider_encrypts_api_key(
        self, service, mock_provider_repo, encryption_service, mock_registry
    ) -> None:
        mock_provider_repo.exists_by_name = AsyncMock(return_value=False)
        request = CreateProviderRequest(
            provider_name="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test-key-12345",
            model="gpt-4",
        )
        await service.create_provider(request)
        saved_provider = mock_provider_repo.save.call_args[0][1]
        assert saved_provider.api_key != "sk-test-key-12345"
        assert encryption_service.decrypt(saved_provider.api_key) == "sk-test-key-12345"
        mock_registry.reload.assert_called_once()

    async def test_create_provider_duplicate_name_raises(self, service, mock_provider_repo) -> None:
        mock_provider_repo.exists_by_name = AsyncMock(return_value=True)
        request = CreateProviderRequest(
            provider_name="dashscope",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-test",
            model="qwen3.5-flash",
        )
        with pytest.raises(BusinessException) as exc:
            await service.create_provider(request)
        assert exc.value.error_code == ErrorCode.PROVIDER_ALREADY_EXISTS


class TestListProviders:
    async def test_list_providers_marks_defaults(
        self, service, mock_provider_repo, mock_global_setting_repo, encryption_service
    ) -> None:
        p1 = _make_provider(provider_id=1, api_key_cipher=encryption_service.encrypt("sk-key1"))
        p2 = _make_provider(
            provider_id=2,
            provider_name="openai",
            api_key_cipher=encryption_service.encrypt("sk-key2"),
            is_default=False,
        )
        mock_provider_repo.list_all = AsyncMock(return_value=[p1, p2])
        mock_global_setting_repo.get_singleton = AsyncMock(return_value=_make_global_setting(chat_id=1, emb_id=1))
        dtos = await service.list_providers()
        assert len(dtos) == 2
        assert dtos[0].default_chat_provider is True
        assert dtos[0].default_embedding_provider is True
        assert dtos[1].default_chat_provider is False
        assert dtos[1].default_embedding_provider is False


class TestUpdateProvider:
    async def test_update_provider_partial_update(self, service, mock_provider_repo, encryption_service) -> None:
        provider = _make_provider(api_key_cipher=encryption_service.encrypt("sk-original"))
        mock_provider_repo.get_by_id = AsyncMock(return_value=provider)
        request = UpdateProviderRequest(model="qwen-max")
        await service.update_provider(1, request)
        assert provider.model == "qwen-max"
        assert provider.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    async def test_update_provider_empty_api_key_rejected(self, service, mock_provider_repo) -> None:
        mock_provider_repo.get_by_id = AsyncMock(return_value=_make_provider())
        request = UpdateProviderRequest(api_key="   ")
        with pytest.raises(BusinessException) as exc:
            await service.update_provider(1, request)
        assert exc.value.error_code == ErrorCode.BAD_REQUEST


class TestDeleteProvider:
    async def test_delete_default_provider_raises(self, service, mock_provider_repo, mock_global_setting_repo) -> None:
        mock_provider_repo.get_by_id = AsyncMock(return_value=_make_provider(provider_id=1))
        mock_global_setting_repo.get_singleton = AsyncMock(return_value=_make_global_setting(chat_id=1, emb_id=1))
        with pytest.raises(BusinessException) as exc:
            await service.delete_provider(1)
        assert exc.value.error_code == ErrorCode.PROVIDER_DEFAULT_CANNOT_DELETE

    async def test_delete_non_default_provider_succeeds(
        self, service, mock_provider_repo, mock_global_setting_repo, mock_registry
    ) -> None:
        mock_provider_repo.get_by_id = AsyncMock(return_value=_make_provider(provider_id=2, is_default=False))
        mock_global_setting_repo.get_singleton = AsyncMock(return_value=_make_global_setting(chat_id=1, emb_id=1))
        await service.delete_provider(2)
        mock_provider_repo.delete.assert_called_once()
        mock_registry.reload.assert_called_once()


class TestReloadProviders:
    async def test_reload_calls_registry_reload(self, service, mock_registry) -> None:
        await service.reload_providers()
        mock_registry.reload.assert_called_once()


class TestUpdateDefaultProvider:
    async def test_update_default_provider_validates_existence(self, service, mock_provider_repo) -> None:
        mock_provider_repo.get_by_id = AsyncMock(return_value=None)
        request = DefaultProviderDTO(default_provider=999)
        with pytest.raises(BusinessException) as exc:
            await service.update_default_provider(request)
        assert exc.value.error_code == ErrorCode.PROVIDER_NOT_FOUND

    async def test_update_default_embedding_provider_requires_embedding_support(
        self, service, mock_provider_repo
    ) -> None:
        mock_provider_repo.get_by_id = AsyncMock(return_value=_make_provider(provider_id=2, supports_embedding=False))
        request = DefaultProviderDTO(default_embedding_provider=2)
        with pytest.raises(BusinessException) as exc:
            await service.update_default_embedding_provider(request)
        assert exc.value.error_code == ErrorCode.BAD_REQUEST

    async def test_update_default_embedding_provider_raises_when_setting_missing(
        self, service, mock_provider_repo, mock_global_setting_repo
    ) -> None:
        mock_provider_repo.get_by_id = AsyncMock(return_value=_make_provider(provider_id=1))
        mock_global_setting_repo.get_singleton = AsyncMock(return_value=None)
        request = DefaultProviderDTO(default_embedding_provider=1)
        with pytest.raises(BusinessException) as exc:
            await service.update_default_embedding_provider(request)
        assert exc.value.error_code == ErrorCode.PROVIDER_CONFIG_READ_FAILED


class TestGetAsrConfig:
    async def test_get_asr_config_masks_api_key(self, service, mock_voice_config_repo, encryption_service) -> None:
        cipher = encryption_service.encrypt("sk-asr-secret-key")
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config(asr_key_cipher=cipher))
        dto = await service.get_asr_config()
        assert dto.masked_api_key == "sk-***key"
        assert dto.url == "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


class TestUpdateAsrConfig:
    async def test_update_asr_config_with_api_key_syncs_tts(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        config = _make_voice_config()
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=config)
        request = AsrConfigRequest(api_key="sk-new-shared-key")
        await service.update_asr_config(request)
        assert encryption_service.decrypt(config.asr_api_key) == "sk-new-shared-key"
        assert encryption_service.decrypt(config.tts_api_key) == "sk-new-shared-key"

    async def test_update_asr_config_without_api_key_does_not_touch_tts(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        original_tts_cipher = encryption_service.encrypt("sk-tts-original")
        config = _make_voice_config(tts_key_cipher=original_tts_cipher)
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=config)
        request = AsrConfigRequest(model="qwen3-asr-new")
        await service.update_asr_config(request)
        assert config.tts_api_key == original_tts_cipher
        assert config.asr_model == "qwen3-asr-new"


class TestGetTtsConfig:
    async def test_get_tts_config_masks_api_key(self, service, mock_voice_config_repo, encryption_service) -> None:
        cipher = encryption_service.encrypt("sk-tts-secret-key")
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config(tts_key_cipher=cipher))
        dto = await service.get_tts_config()
        assert dto.masked_api_key == "sk-***key"
        assert dto.voice == "Cherry"


class TestUpdateTtsConfig:
    async def test_update_tts_config_with_api_key_syncs_asr(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        config = _make_voice_config()
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=config)
        request = TtsConfigRequest(api_key="sk-new-shared-key")
        await service.update_tts_config(request)
        assert encryption_service.decrypt(config.tts_api_key) == "sk-new-shared-key"
        assert encryption_service.decrypt(config.asr_api_key) == "sk-new-shared-key"

    async def test_update_tts_config_without_api_key_does_not_touch_asr(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        original_asr_cipher = encryption_service.encrypt("sk-asr-original")
        config = _make_voice_config(asr_key_cipher=original_asr_cipher)
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=config)
        request = TtsConfigRequest(voice="Loongstella")
        await service.update_tts_config(request)
        assert config.asr_api_key == original_asr_cipher
        assert config.tts_voice == "Loongstella"


class TestTestProvider:
    async def test_test_provider_returns_success(self, service, mock_provider_repo, encryption_service) -> None:
        cipher = encryption_service.encrypt("sk-test")
        mock_provider_repo.get_by_id = AsyncMock(return_value=_make_provider(api_key_cipher=cipher))
        with patch("app.application.llm_provider.service.ChatOpenAI") as mock_chat_class:
            mock_client = AsyncMock()
            mock_client.ainvoke = AsyncMock()
            mock_chat_class.return_value = mock_client
            result = await service.test_provider(1)
        assert result.success is True
        assert result.model == "qwen3.5-flash"

    async def test_test_provider_returns_failure(self, service, mock_provider_repo, encryption_service) -> None:
        cipher = encryption_service.encrypt("sk-test")
        mock_provider_repo.get_by_id = AsyncMock(return_value=_make_provider(api_key_cipher=cipher))
        with patch("app.application.llm_provider.service.ChatOpenAI") as mock_chat_class:
            mock_client = AsyncMock()
            mock_client.ainvoke = AsyncMock(side_effect=RuntimeError("connection refused"))
            mock_chat_class.return_value = mock_client
            result = await service.test_provider(1)
        assert result.success is False
        assert "connection refused" in result.message


class TestTestAsrConfig:
    async def test_test_asr_config_tcp_success(self, service, mock_voice_config_repo) -> None:
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config())
        mock_writer = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        with patch(
            "app.application.llm_provider.service.asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(AsyncMock(), mock_writer),
        ):
            result = await service.test_asr_config()
        assert result.success is True
        assert "dashscope" in result.message

    async def test_test_asr_config_tcp_failure(self, service, mock_voice_config_repo) -> None:
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config())
        with patch(
            "app.application.llm_provider.service.asyncio.open_connection",
            new_callable=AsyncMock,
            side_effect=ConnectionRefusedError("connection refused"),
        ):
            result = await service.test_asr_config()
        assert result.success is False
        assert "connection refused" in result.message
