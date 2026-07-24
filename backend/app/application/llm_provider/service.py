import asyncio
import logging
from urllib.parse import urlparse

from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.llm_provider.schemas import (
    AsrConfigDTO,
    AsrConfigRequest,
    CreateProviderRequest,
    DefaultProviderDTO,
    ProviderDTO,
    ProviderTestResult,
    TtsConfigDTO,
    TtsConfigRequest,
    UpdateProviderRequest,
)
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.ai.encryption import ApiKeyEncryptionService
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.db.models.llm_global_setting import LlmGlobalSetting
from app.infrastructure.db.models.llm_provider import LlmProvider
from app.infrastructure.db.models.voice_config import VoiceConfig
from app.infrastructure.db.repositories.llm_global_setting_repository import LlmGlobalSettingRepository
from app.infrastructure.db.repositories.llm_provider_repository import LlmProviderRepository
from app.infrastructure.db.repositories.voice_config_repository import VoiceConfigRepository

logger = logging.getLogger(__name__)

_TEST_CONNECT_TIMEOUT = 5
_TEST_READ_TIMEOUT = 10


def _mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 6:
        return "***"
    return key[:3] + "***" + key[-3:]


async def seed_default_provider(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(select(LlmProvider))
        if result.scalars().first() is None:
            session.add(
                LlmProvider(
                    provider_name="dashscope",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key="",
                    model="qwen3.5-flash",
                    embedding_model="text-embedding-v3",
                    embedding_dimensions=1024,
                    supports_embedding=True,
                    is_default=True,
                )
            )
            await session.commit()
            logger.info("Seeded default dashscope provider")


async def seed_global_setting(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            select(LlmGlobalSetting).where(LlmGlobalSetting.id == LlmGlobalSetting.SINGLETON_ID)
        )
        if result.scalar_one_or_none() is not None:
            return

        chat_result = await session.execute(
            select(LlmProvider).where(LlmProvider.is_default == True).limit(1)  # noqa: E712
        )
        chat_provider = chat_result.scalars().first()
        if chat_provider is None:
            logger.warning("No default provider found, skipping global setting seed")
            return

        emb_result = await session.execute(
            select(LlmProvider)
            .where(
                LlmProvider.is_default == True,  # noqa: E712
                LlmProvider.supports_embedding == True,  # noqa: E712
            )
            .limit(1)
        )
        emb_provider = emb_result.scalars().first()

        session.add(
            LlmGlobalSetting(
                id=LlmGlobalSetting.SINGLETON_ID,
                default_chat_provider_id=chat_provider.id,
                default_embedding_provider_id=emb_provider.id if emb_provider else None,
            )
        )
        await session.commit()
        logger.info("Seeded llm global setting")


async def seed_voice_config(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(select(VoiceConfig).where(VoiceConfig.id == VoiceConfig.SINGLETON_ID))
        if result.scalar_one_or_none() is not None:
            return
        session.add(VoiceConfig(id=VoiceConfig.SINGLETON_ID))
        await session.commit()
        logger.info("Seeded default voice config")


class LlmProviderService:
    def __init__(
        self,
        session: AsyncSession,
        provider_repository: LlmProviderRepository,
        global_setting_repository: LlmGlobalSettingRepository,
        voice_config_repository: VoiceConfigRepository,
        encryption_service: ApiKeyEncryptionService,
        registry: LlmProviderRegistry,
    ) -> None:
        self._session = session
        self._provider_repository = provider_repository
        self._global_setting_repository = global_setting_repository
        self._voice_config_repository = voice_config_repository
        self._encryption_service = encryption_service
        self._registry = registry

    async def list_providers(self) -> list[ProviderDTO]:
        providers = await self._provider_repository.list_all(self._session)
        setting = await self._global_setting_repository.get_singleton(self._session)
        chat_id = setting.default_chat_provider_id if setting else None
        emb_id = setting.default_embedding_provider_id if setting else None
        return [self._to_dto(p, chat_id, emb_id) for p in providers]

    async def get_provider(self, provider_name: str) -> ProviderDTO:
        provider = await self._provider_repository.get_by_name(self._session, provider_name)
        if provider is None:
            raise BusinessException(ErrorCode.PROVIDER_NOT_FOUND, f"LLM Provider 不存在: {provider_name}")
        setting = await self._global_setting_repository.get_singleton(self._session)
        chat_id = setting.default_chat_provider_id if setting else None
        emb_id = setting.default_embedding_provider_id if setting else None
        return self._to_dto(provider, chat_id, emb_id)

    async def create_provider(self, request: CreateProviderRequest) -> None:
        if await self._provider_repository.exists_by_name(self._session, request.id):
            raise BusinessException(
                ErrorCode.PROVIDER_ALREADY_EXISTS,
                f"Provider '{request.id}' 已存在",
            )
        encrypted_key = self._encryption_service.encrypt(request.api_key)
        embedding_dimensions = request.embedding_dimensions if request.embedding_dimensions is not None else 1024
        supports_embedding = request.supports_embedding if request.supports_embedding is not None else False
        provider = LlmProvider(
            provider_name=request.id,
            base_url=request.base_url,
            api_key=encrypted_key,
            model=request.model,
            embedding_model=request.embedding_model,
            embedding_dimensions=embedding_dimensions,
            supports_embedding=supports_embedding,
            temperature=request.temperature,
        )
        await self._provider_repository.save(self._session, provider)
        await self._session.commit()
        self._registry.reload()
        logger.info("Created provider: name=%s", request.id)

    async def update_provider(self, provider_name: str, request: UpdateProviderRequest) -> None:
        provider = await self._provider_repository.get_by_name(self._session, provider_name)
        if provider is None:
            raise BusinessException(ErrorCode.PROVIDER_NOT_FOUND, f"LLM Provider 不存在: {provider_name}")
        if request.base_url is not None:
            provider.base_url = request.base_url
        if request.model is not None:
            provider.model = request.model
        if request.embedding_model is not None:
            provider.embedding_model = request.embedding_model
        if request.embedding_dimensions is not None:
            provider.embedding_dimensions = request.embedding_dimensions
        if request.supports_embedding is not None:
            provider.supports_embedding = request.supports_embedding
        if request.temperature is not None:
            provider.temperature = request.temperature
        if request.api_key is not None:
            if request.api_key.strip() == "":
                raise BusinessException(ErrorCode.BAD_REQUEST, "apiKey 不能为空字符串")
            provider.api_key = self._encryption_service.encrypt(request.api_key)
        await self._session.commit()
        self._registry.reload()
        logger.info("Updated provider: name=%s", provider_name)

    async def delete_provider(self, provider_name: str) -> None:
        provider = await self._provider_repository.get_by_name(self._session, provider_name)
        if provider is None:
            raise BusinessException(ErrorCode.PROVIDER_NOT_FOUND, f"LLM Provider 不存在: {provider_name}")
        setting = await self._global_setting_repository.get_singleton(self._session)
        if setting is not None and (
            provider.id == setting.default_chat_provider_id or provider.id == setting.default_embedding_provider_id
        ):
            raise BusinessException(
                ErrorCode.PROVIDER_DEFAULT_CANNOT_DELETE,
                f"默认 Provider '{provider_name}' 不可删除，请先切换默认 Provider",
            )
        await self._provider_repository.delete(self._session, provider)
        await self._session.commit()
        self._registry.reload()
        logger.info("Deleted provider: name=%s", provider_name)

    async def test_provider(self, provider_name: str) -> ProviderTestResult:
        provider = await self._provider_repository.get_by_name(self._session, provider_name)
        if provider is None:
            raise BusinessException(ErrorCode.PROVIDER_NOT_FOUND, f"LLM Provider 不存在: {provider_name}")
        api_key = self._encryption_service.decrypt(provider.api_key)
        try:
            client = ChatOpenAI(
                model=provider.model,
                api_key=SecretStr(api_key) if api_key else None,
                base_url=provider.base_url,
                temperature=0,
                timeout=(_TEST_CONNECT_TIMEOUT, _TEST_READ_TIMEOUT),
                max_retries=0,
            )
            await client.ainvoke("Say ok")
            return ProviderTestResult(success=True, message="连接成功", model=provider.model)
        except Exception as e:
            return ProviderTestResult(success=False, message=f"连接失败: {e}", model=provider.model)

    async def reload_providers(self) -> None:
        self._registry.reload()
        logger.info("Manual provider reload triggered")

    async def get_default_provider(self) -> DefaultProviderDTO:
        setting = await self._global_setting_repository.get_singleton(self._session)
        if setting is None:
            return DefaultProviderDTO(default_provider=None, default_embedding_provider=None)
        return DefaultProviderDTO(
            default_provider=await self._resolve_name(setting.default_chat_provider_id),
            default_embedding_provider=await self._resolve_name(setting.default_embedding_provider_id),
        )

    async def update_default_provider(self, request: DefaultProviderDTO) -> None:
        if request.default_provider is None:
            raise BusinessException(ErrorCode.BAD_REQUEST, "defaultProvider 不能为空")
        provider = await self._provider_repository.get_by_name(self._session, request.default_provider)
        if provider is None:
            raise BusinessException(
                ErrorCode.PROVIDER_NOT_FOUND,
                f"LLM Provider 不存在: {request.default_provider}",
            )
        setting = await self._global_setting_repository.get_singleton(self._session)
        if setting is None:
            setting = LlmGlobalSetting(
                id=LlmGlobalSetting.SINGLETON_ID,
                default_chat_provider_id=provider.id,
            )
        else:
            setting.default_chat_provider_id = provider.id
        await self._global_setting_repository.save(self._session, setting)
        await self._session.commit()
        self._registry.reload()
        logger.info("Updated default provider: %s", request.default_provider)

    async def update_default_embedding_provider(self, request: DefaultProviderDTO) -> None:
        if request.default_embedding_provider is None:
            raise BusinessException(ErrorCode.BAD_REQUEST, "defaultEmbeddingProvider 不能为空")
        provider = await self._provider_repository.get_by_name(self._session, request.default_embedding_provider)
        if provider is None:
            raise BusinessException(
                ErrorCode.PROVIDER_NOT_FOUND,
                f"LLM Provider 不存在: {request.default_embedding_provider}",
            )
        if not provider.supports_embedding or not provider.embedding_model:
            raise BusinessException(
                ErrorCode.BAD_REQUEST,
                f"Provider '{request.default_embedding_provider}' 不支持 Embedding，不能设为默认向量服务",
            )
        setting = await self._global_setting_repository.get_singleton(self._session)
        if setting is None:
            raise BusinessException(
                ErrorCode.PROVIDER_CONFIG_READ_FAILED,
                "全局设置未初始化，请先配置默认 Chat Provider",
            )
        setting.default_embedding_provider_id = provider.id
        await self._global_setting_repository.save(self._session, setting)
        await self._session.commit()
        self._registry.reload()
        logger.info("Updated default embedding provider: %s", request.default_embedding_provider)

    async def _resolve_name(self, provider_id: int | None) -> str | None:
        """内部 int 主键 -> 对外字符串标识（provider_name）。默认设置以 int PK 存储，
        对外契约（ADR-0001，对齐 Java）以 provider 名称为 id。"""
        if provider_id is None:
            return None
        provider = await self._provider_repository.get_by_id(self._session, provider_id)
        return provider.provider_name if provider else None

    async def get_asr_config(self) -> AsrConfigDTO:
        config = await self._voice_config_repository.get_singleton(self._session)
        if config is None:
            raise BusinessException(ErrorCode.VOICE_CONFIG_READ_FAILED, "语音服务配置未初始化")
        masked_key = _mask_api_key(self._encryption_service.decrypt(config.asr_api_key))
        return AsrConfigDTO(
            url=config.asr_url,
            model=config.asr_model,
            masked_api_key=masked_key,
            language=config.asr_language,
            format=config.asr_format,
            sample_rate=config.asr_sample_rate,
            enable_turn_detection=config.asr_enable_turn_detection,
            turn_detection_type=config.asr_turn_detection_type,
            turn_detection_threshold=config.asr_turn_detection_threshold,
            turn_detection_silence_duration_ms=config.asr_turn_detection_silence_duration_ms,
        )

    async def update_asr_config(self, request: AsrConfigRequest) -> None:
        config = await self._voice_config_repository.get_singleton(self._session)
        if config is None:
            raise BusinessException(ErrorCode.VOICE_CONFIG_READ_FAILED, "语音服务配置未初始化")
        if request.url is not None:
            config.asr_url = request.url
        if request.model is not None:
            config.asr_model = request.model
        if request.language is not None:
            config.asr_language = request.language
        if request.format is not None:
            config.asr_format = request.format
        if request.sample_rate is not None:
            config.asr_sample_rate = request.sample_rate
        if request.enable_turn_detection is not None:
            config.asr_enable_turn_detection = request.enable_turn_detection
        if request.turn_detection_type is not None:
            config.asr_turn_detection_type = request.turn_detection_type
        if request.turn_detection_threshold is not None:
            config.asr_turn_detection_threshold = request.turn_detection_threshold
        if request.turn_detection_silence_duration_ms is not None:
            config.asr_turn_detection_silence_duration_ms = request.turn_detection_silence_duration_ms
        if request.api_key is not None:
            if request.api_key.strip() == "":
                raise BusinessException(ErrorCode.BAD_REQUEST, "apiKey 不能为空字符串")
            config.asr_api_key = self._encryption_service.encrypt(request.api_key)
        await self._session.commit()
        logger.info("Updated ASR config")

    async def get_tts_config(self) -> TtsConfigDTO:
        config = await self._voice_config_repository.get_singleton(self._session)
        if config is None:
            raise BusinessException(ErrorCode.VOICE_CONFIG_READ_FAILED, "语音服务配置未初始化")
        masked_key = _mask_api_key(self._encryption_service.decrypt(config.tts_api_key))
        return TtsConfigDTO(
            model=config.tts_model,
            masked_api_key=masked_key,
            voice=config.tts_voice,
            format=config.tts_format,
            sample_rate=config.tts_sample_rate,
            mode=config.tts_mode,
            language_type=config.tts_language_type,
            speech_rate=config.tts_speech_rate,
            volume=config.tts_volume,
        )

    async def update_tts_config(self, request: TtsConfigRequest) -> None:
        config = await self._voice_config_repository.get_singleton(self._session)
        if config is None:
            raise BusinessException(ErrorCode.VOICE_CONFIG_READ_FAILED, "语音服务配置未初始化")
        if request.model is not None:
            config.tts_model = request.model
        if request.voice is not None:
            config.tts_voice = request.voice
        if request.format is not None:
            config.tts_format = request.format
        if request.sample_rate is not None:
            config.tts_sample_rate = request.sample_rate
        if request.mode is not None:
            config.tts_mode = request.mode
        if request.language_type is not None:
            config.tts_language_type = request.language_type
        if request.speech_rate is not None:
            config.tts_speech_rate = request.speech_rate
        if request.volume is not None:
            config.tts_volume = request.volume
        if request.api_key is not None:
            if request.api_key.strip() == "":
                raise BusinessException(ErrorCode.BAD_REQUEST, "apiKey 不能为空字符串")
            config.tts_api_key = self._encryption_service.encrypt(request.api_key)
        await self._session.commit()
        logger.info("Updated TTS config")

    async def test_asr_config(self) -> ProviderTestResult:
        config = await self._voice_config_repository.get_singleton(self._session)
        if config is None:
            raise BusinessException(ErrorCode.VOICE_CONFIG_READ_FAILED, "语音服务配置未初始化")
        parsed = urlparse(config.asr_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=_TEST_CONNECT_TIMEOUT,
            )
            writer.close()
            await writer.wait_closed()
            return ProviderTestResult(
                success=True,
                message=f"ASR WebSocket 连接成功: {host}",
                model=config.asr_model,
            )
        except Exception as e:
            return ProviderTestResult(
                success=False,
                message=f"ASR 连接失败: {e}",
                model=config.asr_model,
            )

    async def test_tts_config(self) -> ProviderTestResult:
        config = await self._voice_config_repository.get_singleton(self._session)
        if config is None:
            raise BusinessException(ErrorCode.VOICE_CONFIG_READ_FAILED, "语音服务配置未初始化")
        parsed = urlparse(config.asr_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=_TEST_CONNECT_TIMEOUT,
            )
            writer.close()
            await writer.wait_closed()
            return ProviderTestResult(
                success=True,
                message=f"TTS WebSocket 连接成功: {host}",
                model=config.tts_model,
            )
        except Exception as e:
            return ProviderTestResult(
                success=False,
                message=f"TTS 连接失败: {e}",
                model=config.tts_model,
            )

    def _to_dto(self, provider: LlmProvider, chat_id: int | None, emb_id: int | None) -> ProviderDTO:
        masked_key = _mask_api_key(self._encryption_service.decrypt(provider.api_key))
        return ProviderDTO(
            id=provider.provider_name,
            base_url=provider.base_url,
            masked_api_key=masked_key,
            model=provider.model,
            embedding_model=provider.embedding_model,
            embedding_dimensions=provider.embedding_dimensions,
            supports_embedding=provider.supports_embedding,
            temperature=provider.temperature,
            default_chat_provider=provider.id == chat_id,
            default_embedding_provider=provider.id == emb_id,
        )
