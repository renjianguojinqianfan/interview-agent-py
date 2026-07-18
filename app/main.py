import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware

from app.api.deps import (
    start_resume_analyze_consumer,
    stop_resume_analyze_consumer,
)
from app.api.exception_handlers import register_exception_handlers
from app.api.rate_limit import limiter, rate_limit_exceeded_handler
from app.api.responses import Result
from app.api.routers.interview import router as interview_router
from app.api.routers.resume import router as resume_router
from app.api.routers.skill import router as skill_router
from app.application.llm_provider.service import seed_default_provider
from app.config.settings import settings
from app.infrastructure.db.session import async_session_factory

logger = logging.getLogger(__name__)

_CONSUMER_AUTO_START = "pytest" not in sys.modules


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    try:
        await seed_default_provider(async_session_factory)
    except Exception:
        logger.warning("Database unavailable, skipping provider seed")

    if _CONSUMER_AUTO_START:
        await start_resume_analyze_consumer()

    yield

    if _CONSUMER_AUTO_START:
        await stop_resume_analyze_consumer()


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


@app.get("/health")
async def health() -> Result[dict[str, str]]:
    return Result.success(data={"status": "healthy"})
