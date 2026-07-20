from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True

    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/interview_guide"

    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "interview-guide"
    s3_region: str = "us-east-1"

    ai_api_key: str = ""
    ai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ai_model: str = "qwen3.5-flash"

    secret_key: str = ""
    app_ai_config_encryption_key: str = ""

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:80",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:80",
    ]

    voice_asr_language: str = "zh-CN"
    voice_tts_voice: str = "longxiaochun"
    voice_session_idle_timeout: int = 120
    voice_reconnect_timeout: int = 30

    rate_limit_global: int = 100
    rate_limit_per_ip: int = 30
    rate_limit_per_user: int = 60

    resume_max_file_size: int = 10 * 1024 * 1024
    resume_allowed_content_types: list[str] = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
    ]

    knowledge_base_max_file_size: int = 10 * 1024 * 1024
    knowledge_base_allowed_content_types: list[str] = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
    ]

    rag_default_top_k: int = 5
    rag_min_score: float = 0.3
    rag_probe_window: int = 120
    rag_query_rewrite_enabled: bool = True
    rag_max_context_chars: int = 6000
    rag_history_limit: int = 10


settings = Settings()
