import logging
from collections.abc import AsyncGenerator, Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.interview.evaluation_service import InterviewEvaluationService
from app.application.interview.persistence_service import InterviewPersistenceService
from app.application.interview.question_service import QuestionService
from app.application.interview.session_service import InterviewSessionService
from app.application.interview_schedule.service import ScheduleParseService, ScheduleService
from app.application.knowledgebase.service import KnowledgeBaseService
from app.application.llm_provider.service import LlmProviderService
from app.application.rag.service import RagChatService, RagConfig
from app.application.resume.analysis import ResumeAnalysisService
from app.application.resume.service import ResumeService
from app.application.skill.service import SkillService
from app.application.voice.dialogue_llm import VoiceDialogueLlm
from app.application.voice.service import VoiceEvaluationService, VoiceSessionService
from app.application.voice.ws_handler import VoiceWsOrchestrator
from app.config.settings import settings
from app.graphs.evaluation import EvaluationGraph
from app.infrastructure.ai.encryption import ApiKeyEncryptionService
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.structured_output import StructuredOutputInvoker
from app.infrastructure.db.repositories.interview_repository import InterviewRepository
from app.infrastructure.db.repositories.interview_schedule_repository import InterviewScheduleRepository
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.db.repositories.llm_global_setting_repository import LlmGlobalSettingRepository
from app.infrastructure.db.repositories.llm_provider_repository import LlmProviderRepository
from app.infrastructure.db.repositories.rag_chat_repository import RagChatRepository
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.db.repositories.voice_config_repository import VoiceConfigRepository
from app.infrastructure.db.repositories.voice_interview_repository import VoiceInterviewRepository
from app.infrastructure.db.session import async_session_factory
from app.infrastructure.export.pdf import PdfExportService, WeasyPrintRenderer
from app.infrastructure.parsing.chunker import TokenChunker
from app.infrastructure.parsing.content_type import ContentTypeDetector
from app.infrastructure.parsing.parser import DocumentParser
from app.infrastructure.parsing.text_cleaner import TextCleaner
from app.infrastructure.redis.client import RedisClient, create_redis_client
from app.infrastructure.redis.session_cache import InterviewSessionCache
from app.infrastructure.redis.voice_session_cache import VoiceInterviewSessionCache
from app.infrastructure.scheduler.jobs import (
    cancel_expired_schedules,
    cleanup_voice_zombie_sessions,
    pause_idle_voice_sessions,
)
from app.infrastructure.scheduler.manager import SchedulerManager
from app.infrastructure.skills.loader import SkillLoader
from app.infrastructure.skills.opening_loader import OpeningQuestionLoader
from app.infrastructure.skills.reference_loader import ReferenceLoader
from app.infrastructure.storage.hash import FileHashService
from app.infrastructure.storage.s3 import S3StorageService, create_s3_storage_service
from app.infrastructure.tasks.constants import (
    INTERVIEW_EVALUATE,
    KB_VECTORIZE,
    RESUME_ANALYZE,
    VOICE_EVALUATE,
)
from app.infrastructure.tasks.interview_evaluate_consumer import EvaluateStreamConsumer
from app.infrastructure.tasks.interview_evaluate_producer import EvaluateStreamProducer
from app.infrastructure.tasks.kb_vectorize_consumer import VectorizeStreamConsumer
from app.infrastructure.tasks.kb_vectorize_producer import VectorizeStreamProducer
from app.infrastructure.tasks.resume_analyze_consumer import AnalyzeStreamConsumer
from app.infrastructure.tasks.resume_analyze_producer import AnalyzeStreamProducer
from app.infrastructure.tasks.voice_evaluate_consumer import VoiceEvaluateStreamConsumer
from app.infrastructure.tasks.voice_evaluate_producer import VoiceEvaluateStreamProducer
from app.infrastructure.vector.repository import VectorRepository
from app.infrastructure.voice.asr import QwenAsrClient
from app.infrastructure.voice.config import AsrConfigLoader, TtsConfigLoader
from app.infrastructure.voice.tts import QwenTtsClient

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
_scheduler_manager: SchedulerManager | None = None
_schedule_parse_service: ScheduleParseService | None = None
_voice_repository: VoiceInterviewRepository | None = None
_voice_session_cache: VoiceInterviewSessionCache | None = None
_voice_evaluate_producer: VoiceEvaluateStreamProducer | None = None
_voice_evaluate_consumer: VoiceEvaluateStreamConsumer | None = None
_asr_config_loader: AsrConfigLoader | None = None
_tts_config_loader: TtsConfigLoader | None = None
_voice_dialogue_llm: VoiceDialogueLlm | None = None
_opening_question_loader: OpeningQuestionLoader | None = None

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
        interview_repository=get_interview_repository(),
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
        rag_repository=RagChatRepository(),
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


def get_voice_repository() -> VoiceInterviewRepository:
    global _voice_repository
    if _voice_repository is None:
        _voice_repository = VoiceInterviewRepository()
    return _voice_repository


def get_voice_session_cache() -> VoiceInterviewSessionCache:
    global _voice_session_cache
    if _voice_session_cache is None:
        _voice_session_cache = VoiceInterviewSessionCache(get_redis_client())
    return _voice_session_cache


def get_voice_evaluate_producer() -> VoiceEvaluateStreamProducer:
    global _voice_evaluate_producer
    if _voice_evaluate_producer is None:
        _voice_evaluate_producer = VoiceEvaluateStreamProducer(
            redis_client=get_redis_client(),
            config=VOICE_EVALUATE,
            session_factory=async_session_factory,
            repository=get_voice_repository(),
        )
    return _voice_evaluate_producer


def get_voice_session_service(
    session: AsyncSession = Depends(get_db_session),
) -> VoiceSessionService:
    return VoiceSessionService(
        session=session,
        repository=get_voice_repository(),
        session_cache=get_voice_session_cache(),
        evaluate_producer=get_voice_evaluate_producer(),
        llm_registry=get_llm_registry(),
    )


def get_voice_evaluation_service(
    session: AsyncSession = Depends(get_db_session),
) -> VoiceEvaluationService:
    return VoiceEvaluationService(
        session=session,
        repository=get_voice_repository(),
    )


def get_asr_config_loader() -> AsrConfigLoader:
    global _asr_config_loader
    if _asr_config_loader is None:
        _asr_config_loader = AsrConfigLoader(
            session_factory=async_session_factory,
            repository=VoiceConfigRepository(),
            encryption_service=ApiKeyEncryptionService(settings.app_ai_config_encryption_key),
        )
    return _asr_config_loader


def get_voice_ws_orchestrator_factory() -> Callable[[int], VoiceWsOrchestrator]:
    asr_loader = get_asr_config_loader()
    tts_loader = get_tts_config_loader()
    cache = get_voice_session_cache()
    repository = get_voice_repository()
    dialogue_llm = get_voice_dialogue_llm()
    opening_loader = get_opening_question_loader()

    def _build(session_id: int) -> VoiceWsOrchestrator:
        return VoiceWsOrchestrator(
            session_id=session_id,
            cache=cache,
            repository=repository,
            session_factory=async_session_factory,
            asr_config_loader=asr_loader,
            asr_client_factory=lambda config: QwenAsrClient(config),
            tts_config_loader=tts_loader,
            tts_client_factory=lambda config: QwenTtsClient(config),
            dialogue_llm=dialogue_llm,
            opening_loader=opening_loader,
        )

    return _build


def get_tts_config_loader() -> TtsConfigLoader:
    global _tts_config_loader
    if _tts_config_loader is None:
        _tts_config_loader = TtsConfigLoader(
            session_factory=async_session_factory,
            repository=VoiceConfigRepository(),
            encryption_service=ApiKeyEncryptionService(settings.app_ai_config_encryption_key),
        )
    return _tts_config_loader


def get_voice_dialogue_llm() -> VoiceDialogueLlm:
    global _voice_dialogue_llm
    if _voice_dialogue_llm is None:
        _voice_dialogue_llm = VoiceDialogueLlm(get_llm_registry())
    return _voice_dialogue_llm


def get_opening_question_loader() -> OpeningQuestionLoader:
    global _opening_question_loader
    if _opening_question_loader is None:
        _opening_question_loader = OpeningQuestionLoader()
    return _opening_question_loader


async def start_voice_evaluate_consumer() -> VoiceEvaluateStreamConsumer | None:
    global _voice_evaluate_consumer
    try:
        _voice_evaluate_consumer = VoiceEvaluateStreamConsumer(
            redis_client=get_redis_client(),
            config=VOICE_EVALUATE,
            session_factory=async_session_factory,
            repository=get_voice_repository(),
            resume_repository=ResumeRepository(),
            llm_registry=get_llm_registry(),
            evaluation_graph=get_evaluation_graph(),
        )
        await _voice_evaluate_consumer.start()
        return _voice_evaluate_consumer
    except Exception:
        logger.warning("启动语音评估消费者失败，跳过")
        return None


async def stop_voice_evaluate_consumer() -> None:
    global _voice_evaluate_consumer
    if _voice_evaluate_consumer is not None:
        await _voice_evaluate_consumer.stop()
        _voice_evaluate_consumer = None


def get_schedule_service(
    session: AsyncSession = Depends(get_db_session),
) -> ScheduleService:
    return ScheduleService(
        session=session,
        repository=InterviewScheduleRepository(),
    )


def get_schedule_parse_service() -> ScheduleParseService:
    global _schedule_parse_service
    if _schedule_parse_service is None:
        _schedule_parse_service = ScheduleParseService(
            llm_registry=get_llm_registry(),
            invoker=StructuredOutputInvoker(),
        )
    return _schedule_parse_service


def get_scheduler_manager() -> SchedulerManager:
    global _scheduler_manager
    if _scheduler_manager is None:
        _scheduler_manager = SchedulerManager()
    return _scheduler_manager


async def start_scheduler() -> SchedulerManager | None:
    try:
        manager = get_scheduler_manager()
        manager.register_job(
            cancel_expired_schedules,
            "cron",
            id="cancel_expired_schedules",
            hour="*",
            minute=0,
            args=[async_session_factory],
        )
        manager.register_job(
            pause_idle_voice_sessions,
            "interval",
            id="pause_idle_voice_sessions",
            seconds=30,
            args=[async_session_factory],
        )
        manager.register_job(
            cleanup_voice_zombie_sessions,
            "interval",
            id="cleanup_voice_zombie_sessions",
            minutes=5,
            args=[async_session_factory],
        )
        manager.start()
        return manager
    except Exception:
        logger.warning("启动定时调度器失败，跳过")
        return None


async def stop_scheduler() -> None:
    global _scheduler_manager
    if _scheduler_manager is not None:
        _scheduler_manager.shutdown()
        _scheduler_manager = None
