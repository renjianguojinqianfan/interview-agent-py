"""ASR 连接配置装配测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.errors import BusinessException
from app.infrastructure.db.models.voice_config import VoiceConfig
from app.infrastructure.voice.config import AsrConfigLoader


def _make_session_factory() -> MagicMock:
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


def _voice_config() -> VoiceConfig:
    return VoiceConfig(
        id=1,
        asr_url="wss://host/realtime",
        asr_model="qwen3-asr-flash-realtime",
        asr_api_key="enc",
        asr_language="zh",
        asr_format="pcm",
        asr_sample_rate=16000,
        asr_enable_turn_detection=True,
        asr_turn_detection_type="server_vad",
        asr_turn_detection_threshold=0.0,
        asr_turn_detection_silence_duration_ms=2000,
    )


def _make_loader(config: VoiceConfig | None) -> tuple[AsrConfigLoader, MagicMock]:
    repository = MagicMock()
    repository.get_singleton = AsyncMock(return_value=config)
    encryption = MagicMock()
    encryption.decrypt = MagicMock(return_value="sk-plain")
    return AsrConfigLoader(_make_session_factory(), repository, encryption), encryption


class TestAsrConfigLoader:
    async def test_loads_and_decrypts_api_key(self) -> None:
        loader, encryption = _make_loader(_voice_config())
        result = await loader.load()
        assert result.url == "wss://host/realtime"
        assert result.model == "qwen3-asr-flash-realtime"
        assert result.api_key == "sk-plain"
        assert result.language == "zh"
        assert result.sample_rate == 16000
        assert result.enable_turn_detection is True
        assert result.turn_detection_silence_duration_ms == 2000
        encryption.decrypt.assert_called_once_with("enc")

    async def test_raises_when_config_missing(self) -> None:
        loader, _ = _make_loader(None)
        with pytest.raises(BusinessException):
            await loader.load()
