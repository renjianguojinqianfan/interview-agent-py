import base64
import secrets
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from app.application.llm_provider.schemas import (
    AsrConfigRequest,
    CreateProviderRequest,
    DefaultProviderDTO,
    TtsConfigRequest,
    UpdateProviderRequest,
)
from app.application.llm_provider.service import LlmProviderService, _mask_api_key, seed_default_provider
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
        api_key = secrets.token_urlsafe(16)
        request = CreateProviderRequest(
            id="openai",
            base_url="https://api.openai.com/v1",
            api_key=api_key,
            model="gpt-4",
        )
        await service.create_provider(request)
        saved_provider = mock_provider_repo.save.call_args[0][1]
        assert saved_provider.api_key != api_key
        assert encryption_service.decrypt(saved_provider.api_key) == api_key
        mock_registry.reload.assert_called_once()

    async def test_create_provider_duplicate_name_raises(self, service, mock_provider_repo) -> None:
        mock_provider_repo.exists_by_name = AsyncMock(return_value=True)
        request = CreateProviderRequest(
            id="dashscope",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key=secrets.token_urlsafe(8),
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

    async def test_default_pagination_returns_all(
        self, service, mock_provider_repo, mock_global_setting_repo, encryption_service
    ) -> None:
        providers = [
            _make_provider(provider_id=i, api_key_cipher=encryption_service.encrypt(f"sk-key{i}")) for i in range(1, 6)
        ]
        mock_provider_repo.list_all = AsyncMock(return_value=providers)
        mock_global_setting_repo.get_singleton = AsyncMock(return_value=_make_global_setting(chat_id=1, emb_id=1))

        dtos = await service.list_providers()

        assert len(dtos) == 5

    async def test_limit_restricts_count(
        self, service, mock_provider_repo, mock_global_setting_repo, encryption_service
    ) -> None:
        providers = [
            _make_provider(provider_id=i, api_key_cipher=encryption_service.encrypt(f"sk-key{i}")) for i in range(1, 6)
        ]
        mock_provider_repo.list_all = AsyncMock(return_value=providers)
        mock_global_setting_repo.get_singleton = AsyncMock(return_value=_make_global_setting(chat_id=1, emb_id=1))

        dtos = await service.list_providers(limit=2)

        assert len(dtos) == 2

    async def test_offset_skips_items(
        self, service, mock_provider_repo, mock_global_setting_repo, encryption_service
    ) -> None:
        providers = [
            _make_provider(provider_id=i, api_key_cipher=encryption_service.encrypt(f"sk-key{i}")) for i in range(1, 6)
        ]
        mock_provider_repo.list_all = AsyncMock(return_value=providers)
        mock_global_setting_repo.get_singleton = AsyncMock(return_value=_make_global_setting(chat_id=1, emb_id=1))

        dtos = await service.list_providers(limit=2, offset=3)

        assert len(dtos) == 2


class TestUpdateProvider:
    async def test_update_provider_partial_update(self, service, mock_provider_repo, encryption_service) -> None:
        provider = _make_provider(api_key_cipher=encryption_service.encrypt("sk-original"))
        mock_provider_repo.get_by_name = AsyncMock(return_value=provider)
        request = UpdateProviderRequest(model="qwen-max")
        await service.update_provider("dashscope", request)
        assert provider.model == "qwen-max"
        assert provider.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    async def test_update_provider_empty_api_key_rejected(self, service, mock_provider_repo) -> None:
        mock_provider_repo.get_by_name = AsyncMock(return_value=_make_provider())
        request = UpdateProviderRequest(api_key="   ")
        with pytest.raises(BusinessException) as exc:
            await service.update_provider("dashscope", request)
        assert exc.value.error_code == ErrorCode.BAD_REQUEST


class TestDeleteProvider:
    async def test_delete_default_provider_raises(self, service, mock_provider_repo, mock_global_setting_repo) -> None:
        mock_provider_repo.get_by_name = AsyncMock(return_value=_make_provider(provider_id=1))
        mock_global_setting_repo.get_singleton = AsyncMock(return_value=_make_global_setting(chat_id=1, emb_id=1))
        with pytest.raises(BusinessException) as exc:
            await service.delete_provider("dashscope")
        assert exc.value.error_code == ErrorCode.PROVIDER_DEFAULT_CANNOT_DELETE

    async def test_delete_non_default_provider_succeeds(
        self, service, mock_provider_repo, mock_global_setting_repo, mock_registry
    ) -> None:
        mock_provider_repo.get_by_name = AsyncMock(return_value=_make_provider(provider_id=2, is_default=False))
        mock_global_setting_repo.get_singleton = AsyncMock(return_value=_make_global_setting(chat_id=1, emb_id=1))
        await service.delete_provider("openai")
        mock_provider_repo.delete.assert_called_once()
        mock_registry.reload.assert_called_once()


class TestReloadProviders:
    async def test_reload_calls_registry_reload(self, service, mock_registry) -> None:
        await service.reload_providers()
        mock_registry.reload.assert_called_once()


class TestUpdateDefaultProvider:
    async def test_update_default_provider_validates_existence(self, service, mock_provider_repo) -> None:
        mock_provider_repo.get_by_name = AsyncMock(return_value=None)
        request = DefaultProviderDTO(default_provider="missing")
        with pytest.raises(BusinessException) as exc:
            await service.update_default_provider(request)
        assert exc.value.error_code == ErrorCode.PROVIDER_NOT_FOUND

    async def test_update_default_embedding_provider_requires_embedding_support(
        self, service, mock_provider_repo
    ) -> None:
        mock_provider_repo.get_by_name = AsyncMock(return_value=_make_provider(provider_id=2, supports_embedding=False))
        request = DefaultProviderDTO(default_embedding_provider="openai")
        with pytest.raises(BusinessException) as exc:
            await service.update_default_embedding_provider(request)
        assert exc.value.error_code == ErrorCode.BAD_REQUEST

    async def test_update_default_embedding_provider_raises_when_setting_missing(
        self, service, mock_provider_repo, mock_global_setting_repo
    ) -> None:
        mock_provider_repo.get_by_name = AsyncMock(return_value=_make_provider(provider_id=1))
        mock_global_setting_repo.get_singleton = AsyncMock(return_value=None)
        request = DefaultProviderDTO(default_embedding_provider="dashscope")
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
    async def test_update_asr_config_with_api_key_does_not_touch_tts(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        original_tts_cipher = encryption_service.encrypt("sk-tts-original")
        config = _make_voice_config(tts_key_cipher=original_tts_cipher)
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=config)
        new_asr_key = secrets.token_urlsafe(12)
        request = AsrConfigRequest(api_key=new_asr_key)
        await service.update_asr_config(request)
        assert encryption_service.decrypt(config.asr_api_key) == new_asr_key
        assert config.tts_api_key == original_tts_cipher

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
    async def test_update_tts_config_with_api_key_does_not_touch_asr(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        original_asr_cipher = encryption_service.encrypt("sk-asr-original")
        config = _make_voice_config(asr_key_cipher=original_asr_cipher)
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=config)
        new_tts_key = secrets.token_urlsafe(12)
        request = TtsConfigRequest(api_key=new_tts_key)
        await service.update_tts_config(request)
        assert encryption_service.decrypt(config.tts_api_key) == new_tts_key
        assert config.asr_api_key == original_asr_cipher

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
        mock_provider_repo.get_by_name = AsyncMock(return_value=_make_provider(api_key_cipher=cipher))
        with patch("app.application.llm_provider.service.ChatOpenAI") as mock_chat_class:
            mock_client = AsyncMock()
            mock_client.ainvoke = AsyncMock()
            mock_chat_class.return_value = mock_client
            result = await service.test_provider("dashscope")
        assert result.success is True
        assert result.model == "qwen3.5-flash"

    async def test_test_provider_returns_failure(self, service, mock_provider_repo, encryption_service) -> None:
        cipher = encryption_service.encrypt("sk-test")
        mock_provider_repo.get_by_name = AsyncMock(return_value=_make_provider(api_key_cipher=cipher))
        with patch("app.application.llm_provider.service.ChatOpenAI") as mock_chat_class:
            mock_client = AsyncMock()
            mock_client.ainvoke = AsyncMock(side_effect=RuntimeError("connection refused"))
            mock_chat_class.return_value = mock_client
            result = await service.test_provider("dashscope")
        assert result.success is False
        assert "connection refused" in result.message


class _FakeRealtimeConnection:
    """记录 close 调用的假 realtime 连接（#55 握手测试）。"""

    def __init__(self) -> None:
        self.closed = False

    async def send(self, message: str) -> None:  # pragma: no cover - 协议占位
        return None

    async def recv(self) -> str:  # pragma: no cover - 协议占位
        return ""

    async def close(self) -> None:
        self.closed = True


def _install_connector(
    service: LlmProviderService, error: Exception | None = None
) -> tuple[_FakeRealtimeConnection, list[tuple[str, dict[str, str]]]]:
    """向 service 注入记录调用的假连接器，返回 (连接, 调用记录)。"""
    conn = _FakeRealtimeConnection()
    calls: list[tuple[str, dict[str, str]]] = []

    async def connector(uri: str, headers: dict[str, str]) -> _FakeRealtimeConnection:
        calls.append((uri, headers))
        if error is not None:
            raise error
        return conn

    service._realtime_connector = connector  # type: ignore[assignment]
    return conn, calls


def _invalid_status(code: int) -> InvalidStatus:
    return InvalidStatus(Response(code, "rejected", Headers()))


class TestTestAsrConfig:
    """#55：测试连接必须携带解密 api_key 做真实 WS 握手，不再是裸 TCP 假阳性。"""

    async def test_empty_key_fails_without_connecting(self, service, mock_voice_config_repo) -> None:
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config(asr_key_cipher=""))
        _conn, calls = _install_connector(service)
        result = await service.test_asr_config()
        assert result.success is False
        assert "api_key 未配置" in result.message
        assert calls == []  # key 为空不得发起外部连接

    async def test_auth_failure_reports_auth_error(self, service, mock_voice_config_repo, encryption_service) -> None:
        cipher = encryption_service.encrypt("sk-wrong")
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config(asr_key_cipher=cipher))
        _install_connector(service, error=_invalid_status(401))
        result = await service.test_asr_config()
        assert result.success is False
        assert "鉴权失败" in result.message

    async def test_handshake_success_uses_key_and_model_then_closes(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        cipher = encryption_service.encrypt("sk-asr-real")
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config(asr_key_cipher=cipher))
        conn, calls = _install_connector(service)
        result = await service.test_asr_config()
        assert result.success is True
        assert result.model == "qwen3-asr-flash-realtime"
        uri, headers = calls[0]
        assert "model=qwen3-asr-flash-realtime" in uri
        assert headers["Authorization"] == "Bearer sk-asr-real"
        assert conn.closed is True  # 测试完即断开

    async def test_network_failure_reports_connection_error(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        cipher = encryption_service.encrypt("sk-asr-real")
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config(asr_key_cipher=cipher))
        _install_connector(service, error=OSError("dns resolution failed"))
        result = await service.test_asr_config()
        assert result.success is False
        assert "ASR 连接失败" in result.message


class TestTestTtsConfig:
    """#55：TTS 测试必须用 tts_api_key + tts_model 握手（此前误用 ASR 配置且不验鉴权）。"""

    async def test_empty_key_fails_without_connecting(self, service, mock_voice_config_repo) -> None:
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config(tts_key_cipher=""))
        _conn, calls = _install_connector(service)
        result = await service.test_tts_config()
        assert result.success is False
        assert "api_key 未配置" in result.message
        assert calls == []

    async def test_auth_failure_reports_auth_error(self, service, mock_voice_config_repo, encryption_service) -> None:
        cipher = encryption_service.encrypt("sk-wrong")
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config(tts_key_cipher=cipher))
        _install_connector(service, error=_invalid_status(403))
        result = await service.test_tts_config()
        assert result.success is False
        assert "鉴权失败" in result.message

    async def test_handshake_uses_tts_key_and_tts_model(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        """钉住复制粘贴 bug：必须用 tts_model 构造 uri、tts_api_key 鉴权（url 复用 asr_url 属设计使然）。"""
        asr_cipher = encryption_service.encrypt("sk-asr-key")
        tts_cipher = encryption_service.encrypt("sk-tts-key")
        mock_voice_config_repo.get_singleton = AsyncMock(
            return_value=_make_voice_config(asr_key_cipher=asr_cipher, tts_key_cipher=tts_cipher)
        )
        conn, calls = _install_connector(service)
        result = await service.test_tts_config()
        assert result.success is True
        assert result.model == "qwen3-tts-flash-realtime"
        uri, headers = calls[0]
        assert "model=qwen3-tts-flash-realtime" in uri
        assert uri.startswith("wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
        assert headers["Authorization"] == "Bearer sk-tts-key"
        assert conn.closed is True

    async def test_network_failure_reports_connection_error(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        cipher = encryption_service.encrypt("sk-tts-real")
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config(tts_key_cipher=cipher))
        _install_connector(service, error=TimeoutError())
        result = await service.test_tts_config()
        assert result.success is False
        # 无参 TimeoutError str 为空串，必须回退到异常类名（review HIGH：空消息回归防护）
        assert "TTS 连接失败: TimeoutError" in result.message

    async def test_close_failure_does_not_flip_success(
        self, service, mock_voice_config_repo, encryption_service
    ) -> None:
        """握手成功即定论：close 抛异常不得误报为连接失败（review MEDIUM）。"""
        cipher = encryption_service.encrypt("sk-tts-real")
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=_make_voice_config(tts_key_cipher=cipher))
        conn, _calls = _install_connector(service)
        conn.close = AsyncMock(side_effect=RuntimeError("abort during close"))  # type: ignore[method-assign]
        result = await service.test_tts_config()
        assert result.success is True

    async def test_test_tts_config_raises_when_uninitialized(self, service, mock_voice_config_repo) -> None:
        mock_voice_config_repo.get_singleton = AsyncMock(return_value=None)
        with pytest.raises(BusinessException) as exc:
            await service.test_tts_config()
        assert exc.value.error_code == ErrorCode.VOICE_CONFIG_READ_FAILED


def _make_seed_session(existing_provider: LlmProvider | None = None) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing_provider
    session.execute = AsyncMock(return_value=result)
    return session


def _make_session_factory(session: AsyncMock) -> MagicMock:
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


class TestSeedDefaultProvider:
    """issue #46：首启从环境变量注入 LLM api_key（对齐 Java 版 seedProviders）。"""

    async def test_seed_with_env_key_stores_encrypted(self, encryption_service) -> None:
        session = _make_seed_session()
        await seed_default_provider(_make_session_factory(session), encryption_service, "sk-env-key-123")

        provider = session.add.call_args[0][0]
        assert provider.api_key != "sk-env-key-123"
        assert encryption_service.decrypt(provider.api_key) == "sk-env-key-123"
        session.commit.assert_awaited_once()

    async def test_seed_with_empty_env_keeps_blank_key(self, encryption_service) -> None:
        session = _make_seed_session()
        await seed_default_provider(_make_session_factory(session), encryption_service, "")

        provider = session.add.call_args[0][0]
        assert provider.api_key == ""
        session.commit.assert_awaited_once()

    async def test_seed_skips_when_provider_exists(self, encryption_service) -> None:
        session = _make_seed_session(existing_provider=_make_provider())
        await seed_default_provider(_make_session_factory(session), encryption_service, "sk-env-key-123")

        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    async def test_seed_skips_when_encryption_key_missing(self) -> None:
        """加密 key 未配置时不落空 key（幂等会致 key 永久丢失），跳过本次 seed 待下次启动重试。"""
        session = _make_seed_session()
        await seed_default_provider(_make_session_factory(session), ApiKeyEncryptionService(""), "sk-env-key-123")

        session.add.assert_not_called()
        session.commit.assert_not_awaited()
