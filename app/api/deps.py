from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import settings
from app.infrastructure.ai.encryption import ApiKeyEncryptionService
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.db.session import async_session_factory
from app.infrastructure.redis.client import RedisClient, create_redis_client
from app.infrastructure.storage.s3 import S3StorageService, create_s3_storage_service

_redis_client: RedisClient | None = None
_s3_storage: S3StorageService | None = None
_llm_registry: LlmProviderRegistry | None = None


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


def get_redis_client() -> RedisClient:
    global _redis_client
    if _redis_client is None:
        _redis_client = create_redis_client()
    return _redis_client


def get_s3_storage_service() -> S3StorageService:
    global _s3_storage
    if _s3_storage is None:
        _s3_storage = create_s3_storage_service()
    return _s3_storage


def get_llm_registry(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> LlmProviderRegistry:
    global _llm_registry
    if _llm_registry is None:
        encryption_service = ApiKeyEncryptionService(settings.app_ai_config_encryption_key)
        factory = session_factory or async_session_factory
        _llm_registry = LlmProviderRegistry(encryption_service, factory)
    return _llm_registry
