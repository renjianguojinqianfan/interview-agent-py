from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class VoiceConfig(Base):
    """语音服务配置（单例表，id 固定为 1），存储 ASR/TTS 全量参数。"""

    __tablename__ = "voice_config"

    SINGLETON_ID = 1

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    asr_url: Mapped[str] = mapped_column(
        String(500), nullable=False, default="wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    )
    asr_model: Mapped[str] = mapped_column(String(100), nullable=False, default="qwen3-asr-flash-realtime")
    asr_api_key: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    asr_language: Mapped[str] = mapped_column(String(20), nullable=False, default="zh")
    asr_format: Mapped[str] = mapped_column(String(20), nullable=False, default="pcm")
    asr_sample_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=16000)
    asr_enable_turn_detection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    asr_turn_detection_type: Mapped[str] = mapped_column(String(50), nullable=False, default="server_vad")
    asr_turn_detection_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    asr_turn_detection_silence_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)

    tts_model: Mapped[str] = mapped_column(String(100), nullable=False, default="qwen3-tts-flash-realtime")
    tts_api_key: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    tts_voice: Mapped[str] = mapped_column(String(100), nullable=False, default="Cherry")
    tts_format: Mapped[str] = mapped_column(String(20), nullable=False, default="pcm")
    tts_sample_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=24000)
    tts_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="commit")
    tts_language_type: Mapped[str] = mapped_column(String(50), nullable=False, default="Chinese")
    tts_speech_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    tts_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
