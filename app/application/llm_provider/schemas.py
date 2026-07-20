from app.api.responses import BaseSchema


class ProviderDTO(BaseSchema):
    id: int
    provider_name: str
    base_url: str
    masked_api_key: str
    model: str
    embedding_model: str | None
    embedding_dimensions: int
    supports_embedding: bool
    temperature: float | None
    default_chat_provider: bool
    default_embedding_provider: bool


class CreateProviderRequest(BaseSchema):
    provider_name: str
    base_url: str
    api_key: str
    model: str
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    supports_embedding: bool | None = None
    temperature: float | None = None


class UpdateProviderRequest(BaseSchema):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    supports_embedding: bool | None = None
    temperature: float | None = None


class DefaultProviderDTO(BaseSchema):
    default_provider: int | None = None
    default_embedding_provider: int | None = None


class ProviderTestResult(BaseSchema):
    success: bool
    message: str
    model: str


class AsrConfigDTO(BaseSchema):
    url: str
    model: str
    masked_api_key: str
    language: str
    format: str
    sample_rate: int
    enable_turn_detection: bool
    turn_detection_type: str
    turn_detection_threshold: float
    turn_detection_silence_duration_ms: int


class AsrConfigRequest(BaseSchema):
    url: str | None = None
    model: str | None = None
    api_key: str | None = None
    language: str | None = None
    format: str | None = None
    sample_rate: int | None = None
    enable_turn_detection: bool | None = None
    turn_detection_type: str | None = None
    turn_detection_threshold: float | None = None
    turn_detection_silence_duration_ms: int | None = None


class TtsConfigDTO(BaseSchema):
    model: str
    masked_api_key: str
    voice: str
    format: str
    sample_rate: int
    mode: str
    language_type: str
    speech_rate: float
    volume: int


class TtsConfigRequest(BaseSchema):
    model: str | None = None
    api_key: str | None = None
    voice: str | None = None
    format: str | None = None
    sample_rate: int | None = None
    mode: str | None = None
    language_type: str | None = None
    speech_rate: float | None = None
    volume: int | None = None
