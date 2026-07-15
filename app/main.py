import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.exception_handlers import register_exception_handlers
from app.api.responses import Result
from app.application.llm_provider.service import seed_default_provider
from app.config.settings import settings
from app.infrastructure.db.session import async_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    try:
        await seed_default_provider(async_session_factory)
    except Exception:
        logger.warning("Database unavailable, skipping provider seed")

    yield


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

register_exception_handlers(app)


@app.get("/health")
async def health() -> Result[dict[str, str]]:
    return Result.success(data={"status": "healthy"})
