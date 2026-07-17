import logging
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.resume.analysis import ResumeAnalysisService
from app.application.resume.service import ResumeService
from app.config.settings import settings
from app.infrastructure.ai.encryption import ApiKeyEncryptionService
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.structured_output import StructuredOutputInvoker
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.db.session import async_session_factory
from app.infrastructure.export.pdf import PdfExportService, WeasyPrintRenderer
from app.infrastructure.parsing.content_type import ContentTypeDetector
from app.infrastructure.parsing.parser import DocumentParser
from app.infrastructure.parsing.text_cleaner import TextCleaner
from app.infrastructure.redis.client import RedisClient, create_redis_client
from app.infrastructure.storage.hash import FileHashService
from app.infrastructure.storage.s3 import S3StorageService, create_s3_storage_service
from app.infrastructure.tasks.constants import RESUME_ANALYZE
from app.infrastructure.tasks.resume_analyze_consumer import AnalyzeStreamConsumer
from app.infrastructure.tasks.resume_analyze_producer import AnalyzeStreamProducer

_redis_client: RedisClient | None = None
_s3_storage: S3StorageService | None = None
_llm_registry: LlmProviderRegistry | None = None
_producer: AnalyzeStreamProducer | None = None
_pdf_service: PdfExportService | None = None
_resume_analysis_service: ResumeAnalysisService | None = None
_resume_consumer: AnalyzeStreamConsumer | None = None

logger = logging.getLogger(__name__)


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


def get_resume_producer() -> AnalyzeStreamProducer:
    global _producer
    if _producer is None:
        _producer = AnalyzeStreamProducer(get_redis_client(), RESUME_ANALYZE, async_session_factory, ResumeRepository())
    return _producer


def get_pdf_service() -> PdfExportService:
    global _pdf_service
    if _pdf_service is None:
        _pdf_service = PdfExportService(renderer=WeasyPrintRenderer())
    return _pdf_service


def get_resume_analysis_service() -> ResumeAnalysisService:
    global _resume_analysis_service
    if _resume_analysis_service is None:
        _resume_analysis_service = ResumeAnalysisService(
            llm_registry=get_llm_registry(),
            invoker=StructuredOutputInvoker(),
        )
    return _resume_analysis_service


def get_resume_service(
    session: AsyncSession = Depends(get_db_session),
) -> ResumeService:
    return ResumeService(
        session=session,
        repository=ResumeRepository(),
        parser=DocumentParser(TextCleaner()),
        hash_service=FileHashService(),
        content_detector=ContentTypeDetector(),
        storage=get_s3_storage_service(),
        producer=get_resume_producer(),
        pdf_service=get_pdf_service(),
        allowed_types=settings.resume_allowed_content_types,
        max_file_size=settings.resume_max_file_size,
    )


async def start_resume_analyze_consumer() -> AnalyzeStreamConsumer | None:
    global _resume_consumer
    try:
        _resume_consumer = AnalyzeStreamConsumer(
            redis_client=get_redis_client(),
            config=RESUME_ANALYZE,
            session_factory=async_session_factory,
            repository=ResumeRepository(),
            analysis_service=get_resume_analysis_service(),
        )
        await _resume_consumer.start()
        return _resume_consumer
    except Exception:
        logger.warning("启动简历分析消费者失败，跳过")
        return None


async def stop_resume_analyze_consumer() -> None:
    global _resume_consumer
    if _resume_consumer is not None:
        await _resume_consumer.stop()
        _resume_consumer = None
