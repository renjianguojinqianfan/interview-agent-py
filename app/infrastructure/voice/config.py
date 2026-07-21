"""从 VoiceConfig 单例装配 ASR 连接参数（解密 api_key）。

infrastructure -> infrastructure（DB 仓储 + 加密服务），产出供 asr.py 客户端连接用的
AsrConnectionConfig（含明文 api_key）。
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.ai.encryption import ApiKeyEncryptionService
from app.infrastructure.db.repositories.voice_config_repository import VoiceConfigRepository
from app.infrastructure.voice.asr import AsrConnectionConfig
from app.infrastructure.voice.tts import TtsConnectionConfig


class AsrConfigLoader:
    """读取 VoiceConfig 单例并解密 api_key，装配为 AsrConnectionConfig。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        repository: VoiceConfigRepository,
        encryption_service: ApiKeyEncryptionService,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository
        self._encryption_service = encryption_service

    async def load(self) -> AsrConnectionConfig:
        async with self._session_factory() as session:
            config = await self._repository.get_singleton(session)
            if config is None:
                raise BusinessException(ErrorCode.VOICE_CONFIG_READ_FAILED, "语音服务配置未初始化")
            return AsrConnectionConfig(
                url=config.asr_url,
                model=config.asr_model,
                api_key=self._encryption_service.decrypt(config.asr_api_key),
                language=config.asr_language,
                audio_format=config.asr_format,
                sample_rate=config.asr_sample_rate,
                enable_turn_detection=config.asr_enable_turn_detection,
                turn_detection_type=config.asr_turn_detection_type,
                turn_detection_threshold=config.asr_turn_detection_threshold,
                turn_detection_silence_duration_ms=config.asr_turn_detection_silence_duration_ms,
            )


class TtsConfigLoader:
    """读取 VoiceConfig 单例并解密 tts_api_key，装配为 TtsConnectionConfig（url 复用 asr_url）。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        repository: VoiceConfigRepository,
        encryption_service: ApiKeyEncryptionService,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository
        self._encryption_service = encryption_service

    async def load(self) -> TtsConnectionConfig:
        async with self._session_factory() as session:
            config = await self._repository.get_singleton(session)
            if config is None:
                raise BusinessException(ErrorCode.VOICE_CONFIG_READ_FAILED, "语音服务配置未初始化")
            return TtsConnectionConfig(
                url=config.asr_url,
                model=config.tts_model,
                api_key=self._encryption_service.decrypt(config.tts_api_key),
                voice=config.tts_voice,
                mode=config.tts_mode,
                response_format=config.tts_format,
                sample_rate=config.tts_sample_rate,
                speech_rate=config.tts_speech_rate,
                volume=config.tts_volume,
                language_type=config.tts_language_type,
            )
