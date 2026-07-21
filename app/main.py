import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware

from app.api.deps import (
    start_interview_evaluate_consumer,
    start_kb_vectorize_consumer,
    start_resume_analyze_consumer,
    start_scheduler,
    start_voice_evaluate_consumer,
    stop_interview_evaluate_consumer,
    stop_kb_vectorize_consumer,
    stop_resume_analyze_consumer,
    stop_scheduler,
    stop_voice_evaluate_consumer,
)
from app.api.exception_handlers import register_exception_handlers
from app.api.rate_limit import limiter, rate_limit_exceeded_handler
from app.api.responses import Result
from app.api.routers.interview import router as interview_router
from app.api.routers.interview_schedule import router as interview_schedule_router
from app.api.routers.knowledgebase import router as knowledgebase_router
from app.api.routers.llm_provider import router as llm_provider_router
from app.api.routers.rag_chat import router as rag_chat_router
from app.api.routers.resume import router as resume_router
from app.api.routers.skill import router as skill_router
from app.api.routers.voice_interview import router as voice_interview_router
from app.api.routers.voice_ws import router as voice_ws_router
from app.application.llm_provider.service import seed_default_provider, seed_global_setting, seed_voice_config
from app.config.settings import settings
from app.infrastructure.db.session import async_session_factory

logger = logging.getLogger(__name__)

_CONSUMER_AUTO_START = "pytest" not in sys.modules


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    try:
        await seed_default_provider(async_session_factory)
        await seed_global_setting(async_session_factory)
        await seed_voice_config(async_session_factory)
    except Exception:
        logger.warning("Database unavailable, skipping provider seed")

    if _CONSUMER_AUTO_START:
        await start_resume_analyze_consumer()
        await start_interview_evaluate_consumer()
        await start_kb_vectorize_consumer()
        await start_voice_evaluate_consumer()
        await start_scheduler()

    yield

    if _CONSUMER_AUTO_START:
        await stop_scheduler()
        await stop_voice_evaluate_consumer()
        await stop_resume_analyze_consumer()
        await stop_interview_evaluate_consumer()
        await stop_kb_vectorize_consumer()


app = FastAPI(
    title="interview-agent-py",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIASGIMiddleware)

register_exception_handlers(app)
app.include_router(resume_router)
app.include_router(skill_router)
app.include_router(interview_router)
app.include_router(interview_schedule_router)
app.include_router(knowledgebase_router)
app.include_router(rag_chat_router)
app.include_router(llm_provider_router)
app.include_router(voice_interview_router)
app.include_router(voice_ws_router)


@app.get("/health")
async def health() -> Result[dict[str, str]]:
    return Result.success(data={"status": "healthy"})
