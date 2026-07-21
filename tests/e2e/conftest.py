"""端到端集成测试 fixtures：真实 Postgres（docker compose up -d postgres + alembic upgrade head）。

DB 不可达/未迁移时自动 skip —— 保证 make verify 在无基础设施的 CI 仍全绿，
而本地起了 docker 时真实运行（#20 端到端集成测试）。每个测试前清空相关表以隔离。
每个测试用独立 engine，避免 pytest-asyncio 函数级事件循环复用模块级 async engine 的冲突。
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config.settings import settings
from app.infrastructure.db.models import (  # noqa: F401  注册全部 ORM 到 Base.metadata（解析跨表外键）
    interview,
    interview_schedule,
    knowledge_base,
    llm_global_setting,
    llm_provider,
    rag_chat,
    resume,
    voice_config,
    voice_interview,
)

# 端到端测试涉及的表，每个测试前 TRUNCATE 隔离（CASCADE 处理 FK 子表，如 interview_answers）。
_E2E_TABLES = "interview_schedule, voice_interview_sessions, interview_sessions"


async def _truncate(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_E2E_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def live_session_factory() -> AsyncIterator[async_sessionmaker]:
    """真实 Postgres 会话工厂；连不上或未迁移则 skip。"""
    engine = create_async_engine(settings.database_url)
    try:
        await _truncate(engine)
    except Exception:
        await engine.dispose()
        pytest.skip("Postgres 不可用或未迁移：docker compose up -d postgres && uv run alembic upgrade head")
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
