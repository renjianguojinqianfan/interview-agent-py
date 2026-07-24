"""集成竖切测试 fixtures（ADR-0016）：真 app（TestClient）+ 真 Postgres/Redis，仅假 AI（LLM/ASR/TTS）。

竖切从"真 HTTP 请求"起步，穿过真实路由 / 校验 / Result 包裹 / 服务编排 / 仓储，断言真库落数据 ——
补足分层单测（api mock 服务、application mock 仓储、infrastructure mock session）无法覆盖的
"按钮 -> 数据"整链（见 ADR-0016 病灶）。与 e2e 同惯例：CI 缺基础设施则 fail、本地无 docker 则 skip；
每测试前 TRUNCATE 隔离。不以 context manager 方式用 TestClient，故不触发 lifespan（消费者/调度器不启动）。
"""

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.rate_limit import limiter
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
from app.main import app

# 集成竖切涉及的数据表；每测试前 TRUNCATE CASCADE 隔离（子表如 interview_answers 由 CASCADE 处理）。
_INTEGRATION_TABLES = (
    "interview_sessions, interview_schedule, knowledge_bases, "
    "rag_chat_sessions, resumes, voice_interview_sessions, vector_store"
)


def _require_infra_or_skip(reason: str) -> None:
    """基础设施（Postgres/Redis）不可用时的处置（ADR-0016）：CI fail（真库必跑）/ 本地 skip（体验不退化）。"""
    if os.environ.get("CI"):
        pytest.fail(reason)
    pytest.skip(reason)


def _truncate_all() -> None:
    """在独立事件循环 + 独立 engine 中清空相关表，避免与 TestClient 的 async portal 事件循环纠缠。"""

    async def _run() -> None:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"TRUNCATE {_INTEGRATION_TABLES} RESTART IDENTITY CASCADE"))
        finally:
            await engine.dispose()

    asyncio.run(_run())


@pytest.fixture(scope="session")
def _live_app_client() -> Iterator[TestClient]:
    """会话级 TestClient（context manager）：单一持久事件循环，使 app 的 async Redis/DB 单例跨请求与跨测试保持有效。

    以 context manager 进入会触发 lifespan，但 pytest 下 _CONSUMER_AUTO_START=False，消费者/调度器不启动（见 main.py）。
    不用逐测试 context manager：逐测试新建 portal 会为每个测试新建事件循环，
    而 app 的单例连接绑定首次循环，后续测试将命中已关闭循环。
    """
    # 测试用对象存储凭证：本地 MinIO 默认 minioadmin/minioadmin；CI/环境经 env 注入则保留原值。
    settings.s3_access_key = settings.s3_access_key or "minioadmin"
    settings.s3_secret_key = settings.s3_secret_key or "minioadmin"
    with TestClient(app) as client:
        yield client


@pytest.fixture
def integration_client(_live_app_client: TestClient) -> Iterator[TestClient]:
    """真 app + 真库的集成客户端：复用会话级持久事件循环，每测试前清库 + 复位限流器，测试后清理依赖覆盖。"""
    try:
        _truncate_all()
    except Exception:
        _require_infra_or_skip("Postgres 不可用或未迁移：docker compose up -d postgres && uv run alembic upgrade head")

    limiter.reset()
    try:
        yield _live_app_client
    finally:
        limiter.reset()
        app.dependency_overrides.clear()
