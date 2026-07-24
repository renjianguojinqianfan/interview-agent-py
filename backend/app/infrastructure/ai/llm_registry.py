import logging

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.ai.embeddings import create_embeddings
from app.infrastructure.ai.encryption import ApiKeyEncryptionService
from app.infrastructure.ai.provider_snapshot import ProviderSnapshot
from app.infrastructure.db.models.llm_global_setting import LlmGlobalSetting
from app.infrastructure.db.models.llm_provider import LlmProvider

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 10
_READ_TIMEOUT = 300
_MAX_RETRIES = 2
_DEFAULT_TEMPERATURE = 0.2

_RECOMMENDED_EMBEDDING_MODELS: dict[str, str] = {
    "dashscope": "text-embedding-v3",
    "glm": "embedding-3",
    "zhipu": "embedding-3",
    "baidu": "Embedding-V1",
    "minimax": "embo-01",
}


class LlmProviderRegistry:
    def __init__(
        self,
        encryption_service: ApiKeyEncryptionService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._encryption_service = encryption_service
        self._session_factory = session_factory
        self._client_cache: dict[str, ChatOpenAI] = {}
        self._embedding_cache: dict[int, OpenAIEmbeddings] = {}

    async def get_chat_client(self, provider_id: int | None = None) -> ChatOpenAI:
        resolved_id = await self._resolve_chat_provider_id(provider_id)
        cache_key = f"{resolved_id}:default"
        if cache_key not in self._client_cache:
            self._client_cache[cache_key] = await self._create_chat_client(resolved_id)
        return self._client_cache[cache_key]

    async def get_plain_chat_client(self, provider_id: int | None = None) -> ChatOpenAI:
        resolved_id = await self._resolve_chat_provider_id(provider_id)
        cache_key = f"{resolved_id}:plain"
        if cache_key not in self._client_cache:
            self._client_cache[cache_key] = await self._create_chat_client(resolved_id)
        return self._client_cache[cache_key]

    async def get_voice_chat_client(self, provider_id: int | None = None) -> ChatOpenAI:
        resolved_id = await self._resolve_chat_provider_id(provider_id)
        cache_key = f"{resolved_id}:voice"
        if cache_key not in self._client_cache:
            self._client_cache[cache_key] = await self._create_chat_client(resolved_id, streaming=True)
        return self._client_cache[cache_key]

    async def get_streaming_chat_client(self, provider_id: int | None = None) -> ChatOpenAI:
        resolved_id = await self._resolve_chat_provider_id(provider_id)
        cache_key = f"{resolved_id}:stream"
        if cache_key not in self._client_cache:
            self._client_cache[cache_key] = await self._create_chat_client(resolved_id, streaming=True)
        return self._client_cache[cache_key]

    async def get_embeddings(self, provider_id: int | None = None) -> OpenAIEmbeddings:
        resolved_id = await self._resolve_embedding_provider_id(provider_id)
        if resolved_id not in self._embedding_cache:
            config = await self._load_provider(resolved_id)
            self._embedding_cache[resolved_id] = create_embeddings(config)
        return self._embedding_cache[resolved_id]

    async def get_default_embeddings(self) -> OpenAIEmbeddings:
        return await self.get_embeddings()

    async def resolve_provider_id_by_name(self, provider_name: str | None) -> int | None:
        """将对外字符串供应商标识（= provider_name，ADR-0015）解析为内部 int 主键。

        None/空 → None（调用方回退默认）；传入不存在的名称 → 抛 PROVIDER_NOT_FOUND（非静默回退）。
        """
        if not provider_name:
            return None
        async with self._session_factory() as session:
            result = await session.execute(select(LlmProvider.id).where(LlmProvider.provider_name == provider_name))
            provider_id = result.scalar_one_or_none()
        if provider_id is None:
            raise BusinessException(ErrorCode.PROVIDER_NOT_FOUND, f"未找到 LLM Provider: {provider_name}")
        return int(provider_id)

    def reload(self) -> None:
        size = len(self._client_cache) + len(self._embedding_cache)
        self._client_cache.clear()
        self._embedding_cache.clear()
        logger.info("LlmProviderRegistry cache cleared (%d entries)", size)

    async def _resolve_chat_provider_id(self, provider_id: int | None) -> int:
        if provider_id is not None:
            return provider_id
        return await self._find_default_chat_provider_id()

    async def _resolve_embedding_provider_id(self, provider_id: int | None) -> int:
        if provider_id is not None:
            return provider_id
        return await self._find_default_embedding_provider_id()

    async def _find_default_chat_provider_id(self) -> int:
        setting = await self._get_global_setting()
        if setting.default_chat_provider_id is None:
            raise BusinessException(
                ErrorCode.PROVIDER_NOT_FOUND,
                "未找到默认 LLM Provider，请先配置",
            )
        return setting.default_chat_provider_id

    async def _find_default_embedding_provider_id(self) -> int:
        setting = await self._get_global_setting()
        if setting.default_embedding_provider_id is None:
            raise BusinessException(
                ErrorCode.PROVIDER_NOT_FOUND,
                "未找到默认 Embedding Provider，请先配置",
            )
        return setting.default_embedding_provider_id

    async def _get_global_setting(self) -> LlmGlobalSetting:
        async with self._session_factory() as session:
            result = await session.execute(
                select(LlmGlobalSetting).where(LlmGlobalSetting.id == LlmGlobalSetting.SINGLETON_ID)
            )
            setting = result.scalar_one_or_none()
            if setting is None:
                raise BusinessException(
                    ErrorCode.PROVIDER_NOT_FOUND,
                    "全局 LLM 配置未初始化，请先配置默认 Provider",
                )
            return setting

    async def _load_provider(self, provider_id: int) -> ProviderSnapshot:
        async with self._session_factory() as session:
            result = await session.execute(select(LlmProvider).where(LlmProvider.id == provider_id))
            entity = result.scalars().first()
            if entity is None:
                raise BusinessException(
                    ErrorCode.PROVIDER_NOT_FOUND,
                    f"未找到 LLM Provider: {provider_id}",
                )
            return ProviderSnapshot(
                id=entity.id,
                base_url=entity.base_url,
                api_key=self._encryption_service.decrypt(entity.api_key),
                model=entity.model,
                embedding_model=entity.embedding_model,
                embedding_dimensions=entity.embedding_dimensions,
                supports_embedding=entity.supports_embedding,
                temperature=entity.temperature,
            )

    async def _create_chat_client(self, provider_id: int, streaming: bool = False) -> ChatOpenAI:
        config = await self._load_provider(provider_id)
        logger.info(
            "Creating ChatOpenAI - provider_id=%s, base_url=%s, model=%s, streaming=%s",
            provider_id,
            config.base_url,
            config.model,
            streaming,
        )
        return ChatOpenAI(
            model=config.model,
            api_key=SecretStr(config.api_key) if config.api_key else None,
            base_url=config.base_url,
            temperature=config.temperature if config.temperature is not None else _DEFAULT_TEMPERATURE,
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            max_retries=_MAX_RETRIES,
            streaming=streaming,
        )

    def get_recommended_embedding_model(self, provider_name: str) -> str | None:
        return _RECOMMENDED_EMBEDDING_MODELS.get(provider_name.lower())
