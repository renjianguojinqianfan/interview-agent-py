import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.exception_handlers import register_exception_handlers
from app.api.responses import Result
from app.application.llm_provider.service import seed_default_provider

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    try:
        await seed_default_provider()
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
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:80",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:80",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


@app.get("/health")
async def health() -> Result[dict[str, str]]:
    return Result.success(data={"status": "healthy"})
