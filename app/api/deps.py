import logging
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.interview.evaluation_service import InterviewEvaluationService
from app.application.interview.persistence_service import InterviewPersistenceService
from app.application.interview.question_service import QuestionService
from app.application.interview.session_service import InterviewSessionService
from app.application.knowledgebase.service import KnowledgeBaseService
from app.application.llm_provider.service import LlmProviderService
from app.application.rag.service import RagChatService, RagConfig
from app.application.resume.analysis import ResumeAnalysisService
from app.application.resume.service import ResumeService
from app.application.skill.service import SkillService
from app.config.settings import settings
from app.graphs.evaluation import EvaluationGraph
from app.infrastructure.ai.encryption import ApiKeyEncryptionService
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.structured_output import StructuredOutputInvoker
from app.infrastructure.db.repositories.interview_repository import InterviewRepository
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.db.repositories.llm_global_setting_repository import LlmGlobalSettingRepository
from app.infrastructure.db.repositories.llm_provider_repository import LlmProviderRepository
from app.infrastructure.db.repositories.rag_chat_repository import RagChatRepository
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.db.repositories.voice_config_repository import VoiceConfigRepository
from app.infrastructure.db.session import async_session_factory
from app.infrastructure.export.pdf import PdfExportService, WeasyPrintRenderer
from app.infrastructure.parsing.chunker import TokenChunker
from app.infrastructure.parsing.content_type import ContentTypeDetector
from app.infrastructure.parsing.parser import DocumentParser
from app.infrastructure.parsing.text_cleaner import TextCleaner
from app.infrastructure.redis.client import RedisClient, create_redis_client
from app.infrastructure.redis.session_cache import InterviewSessionCache
from app.infrastructure.skills.loader import SkillLoader
from app.infrastructure.skills.reference_loader import ReferenceLoader
from app.infrastructure.storage.hash import FileHashService
from app.infrastructure.storage.s3 import S3StorageService, create_s3_storage_service
from app.infrastructure.tasks.constants import INTERVIEW_EVALUATE, KB_VECTORIZE, RESUME_ANALYZE
from app.infrastructure.tasks.interview_evaluate_consumer import EvaluateStreamConsumer
from app.infrastructure.tasks.interview_evaluate_producer import EvaluateStreamProducer
from app.infrastructure.tasks.kb_vectorize_consumer import VectorizeStreamConsumer
from app.infrastructure.tasks.kb_vectorize_producer import VectorizeStreamProducer
from app.infrastructure.tasks.resume_analyze_consumer import AnalyzeStreamConsumer
from app.infrastructure.tasks.resume_analyze_producer import AnalyzeStreamProducer
from app.infrastructure.vector.repository import VectorRepository

_redis_client: RedisClient | None = None
_s3_storage: S3StorageService | None = None
_llm_registry: LlmProviderRegistry | None = None
_producer: AnalyzeStreamProducer | None = None
_pdf_service: PdfExportService | None = None
_resume_analysis_service: ResumeAnalysisService | None = None
_resume_consumer: AnalyzeStreamConsumer | None = None
_skill_service: SkillService | None = None
_interview_repository: InterviewRepository | None = None
_interview_session_cache: InterviewSessionCache | None = None
_evaluate_producer: EvaluateStreamProducer | None = None
_question_service: QuestionService | None = None
_evaluation_graph: EvaluationGraph | None = None
_interview_evaluate_consumer: EvaluateStreamConsumer | None = None
_kb_vectorize_producer: VectorizeStreamProducer | None = None
_kb_vectorize_consumer: VectorizeStreamConsumer | None = None
_token_chunker: TokenChunker | None = None

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


def get_llm_provider_service(
    session: AsyncSession = Depends(get_db_session),
) -> LlmProviderService:
    return LlmProviderService(
        session=session,
        provider_repository=LlmProviderRepository(),
        global_setting_repository=LlmGlobalSettingRepository(),
        voice_config_repository=VoiceConfigRepository(),
        encryption_service=ApiKeyEncryptionService(settings.app_ai_config_encryption_key),
        registry=get_llm_registry(),
    )


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


def get_skill_service() -> SkillService:
    global _skill_service
    if _skill_service is None:
        _skill_service = SkillService(
            loader=SkillLoader(),
            llm_registry=get_llm_registry(),
            invoker=StructuredOutputInvoker(),
        )
    return _skill_service


def get_token_chunker() -> TokenChunker:
    global _token_chunker
    if _token_chunker is None:
        _token_chunker = TokenChunker()
    return _token_chunker


def get_kb_vectorize_producer() -> VectorizeStreamProducer:
    global _kb_vectorize_producer
    if _kb_vectorize_producer is None:
        _kb_vectorize_producer = VectorizeStreamProducer(
            get_redis_client(), KB_VECTORIZE, async_session_factory, KnowledgeBaseRepository()
        )
    return _kb_vectorize_producer


def get_knowledge_base_service(
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeBaseService:
    return KnowledgeBaseService(
        session=session,
        repository=KnowledgeBaseRepository(),
        parser=DocumentParser(TextCleaner()),
        hash_service=FileHashService(),
        content_detector=ContentTypeDetector(),
        storage=get_s3_storage_service(),
        producer=get_kb_vectorize_producer(),
        vector_repository=VectorRepository(),
        allowed_types=settings.knowledge_base_allowed_content_types,
        max_file_size=settings.knowledge_base_max_file_size,
    )


def get_rag_chat_service(
    session: AsyncSession = Depends(get_db_session),
) -> RagChatService:
    return RagChatService(
        session=session,
        session_factory=async_session_factory,
        repository=RagChatRepository(),
        kb_repository=KnowledgeBaseRepository(),
        vector_repository=VectorRepository(),
        llm_registry=get_llm_registry(),
        config=RagConfig(
            min_score=settings.rag_min_score,
            probe_window=settings.rag_probe_window,
            query_rewrite_enabled=settings.rag_query_rewrite_enabled,
            max_context_chars=settings.rag_max_context_chars,
            history_limit=settings.rag_history_limit,
        ),
    )


async def start_kb_vectorize_consumer() -> VectorizeStreamConsumer | None:
    global _kb_vectorize_consumer
    try:
        _kb_vectorize_consumer = VectorizeStreamConsumer(
            redis_client=get_redis_client(),
            config=KB_VECTORIZE,
            session_factory=async_session_factory,
            repository=KnowledgeBaseRepository(),
            vector_repository=VectorRepository(),
            chunker=get_token_chunker(),
            llm_registry=get_llm_registry(),
        )
        await _kb_vectorize_consumer.start()
        return _kb_vectorize_consumer
    except Exception:
        logger.warning("启动知识库向量化消费者失败，跳过")
        return None


async def stop_kb_vectorize_consumer() -> None:
    global _kb_vectorize_consumer
    if _kb_vectorize_consumer is not None:
        await _kb_vectorize_consumer.stop()
        _kb_vectorize_consumer = None


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


def get_evaluation_graph() -> EvaluationGraph:
    global _evaluation_graph
    if _evaluation_graph is None:
        _evaluation_graph = EvaluationGraph(invoker=StructuredOutputInvoker())
    return _evaluation_graph


async def start_interview_evaluate_consumer() -> EvaluateStreamConsumer | None:
    global _interview_evaluate_consumer
    try:
        _interview_evaluate_consumer = EvaluateStreamConsumer(
            redis_client=get_redis_client(),
            config=INTERVIEW_EVALUATE,
            session_factory=async_session_factory,
            repository=get_interview_repository(),
            resume_repository=ResumeRepository(),
            llm_registry=get_llm_registry(),
            evaluation_graph=get_evaluation_graph(),
        )
        await _interview_evaluate_consumer.start()
        return _interview_evaluate_consumer
    except Exception:
        logger.warning("启动面试评估消费者失败，跳过")
        return None


async def stop_interview_evaluate_consumer() -> None:
    global _interview_evaluate_consumer
    if _interview_evaluate_consumer is not None:
        await _interview_evaluate_consumer.stop()
        _interview_evaluate_consumer = None


def get_interview_repository() -> InterviewRepository:
    global _interview_repository
    if _interview_repository is None:
        _interview_repository = InterviewRepository()
    return _interview_repository


def get_interview_session_cache() -> InterviewSessionCache:
    global _interview_session_cache
    if _interview_session_cache is None:
        _interview_session_cache = InterviewSessionCache(get_redis_client())
    return _interview_session_cache


def get_evaluate_producer() -> EvaluateStreamProducer:
    global _evaluate_producer
    if _evaluate_producer is None:
        _evaluate_producer = EvaluateStreamProducer(
            redis_client=get_redis_client(),
            config=INTERVIEW_EVALUATE,
            session_factory=async_session_factory,
            repository=get_interview_repository(),
        )
    return _evaluate_producer


def get_question_service() -> QuestionService:
    global _question_service
    if _question_service is None:
        _question_service = QuestionService(
            skill_loader=SkillLoader(),
            reference_loader=ReferenceLoader(),
            llm_registry=get_llm_registry(),
            invoker=StructuredOutputInvoker(),
        )
    return _question_service


def get_interview_session_service(
    session: AsyncSession = Depends(get_db_session),
) -> InterviewSessionService:
    return InterviewSessionService(
        session=session,
        question_service=get_question_service(),
        persistence_service=InterviewPersistenceService(session, get_interview_repository()),
        session_cache=get_interview_session_cache(),
        evaluate_producer=get_evaluate_producer(),
        resume_repository=ResumeRepository(),
    )


def get_interview_evaluation_service(
    session: AsyncSession = Depends(get_db_session),
) -> InterviewEvaluationService:
    return InterviewEvaluationService(
        session=session,
        repository=get_interview_repository(),
        pdf_service=get_pdf_service(),
    )
