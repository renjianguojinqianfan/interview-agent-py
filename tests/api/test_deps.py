from app.api.deps import get_db_session, get_llm_registry, get_redis_client, get_s3_storage_service
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.storage.s3 import S3StorageService


class TestGetDbSession:
    async def test_yields_async_session(self) -> None:
        async for session in get_db_session():
            assert session is not None
            break


class TestGetLlmRegistry:
    def test_returns_llm_provider_registry(self) -> None:
        import app.api.deps as deps

        deps._llm_registry = None
        registry = get_llm_registry()
        assert isinstance(registry, LlmProviderRegistry)
        assert get_llm_registry() is registry
        deps._llm_registry = None


class TestGetRedisClient:
    def test_returns_redis_client(self) -> None:
        import app.api.deps as deps

        deps._redis_client = None
        client = get_redis_client()
        assert isinstance(client, RedisClient)
        assert get_redis_client() is client
        deps._redis_client = None


class TestGetS3StorageService:
    def test_returns_s3_storage_service(self) -> None:
        import app.api.deps as deps

        deps._s3_storage = None
        service = get_s3_storage_service()
        assert isinstance(service, S3StorageService)
        assert get_s3_storage_service() is service
        deps._s3_storage = None
