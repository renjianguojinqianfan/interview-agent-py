"""异步管线入口集成竖切（ADR-0016）：真 HTTP -> 真解析 -> 真 S3(MinIO) -> 真库 -> 真 Redis 入队。

覆盖两条优先级最高的"上传 -> 落库 + 入队异步处理"按钮流（上传路径本身不含 LLM，分析/向量化在
消费侧，已由 e2e 覆盖）：断言真库落记录 + 状态置 PENDING + 解析文本入库。分层单测（api mock 服务）
证明不了"上传后真的存了文件、落了库、置了 PENDING"，此竖切正是 ADR-0016 要补的整链。
"""

import asyncio
import socket
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import settings
from app.infrastructure.db.models.knowledge_base import KnowledgeBase
from app.infrastructure.db.models.resume import Resume


@pytest.fixture(autouse=True)
def _require_object_store() -> None:
    """上传竖切依赖对象存储(MinIO)；端口不可达则 skip。

    CI 暂未挂 MinIO service（MinIO 难以作为 GitHub services 容器运行），故此处用普通 skip 而非 fail-in-CI；
    本地 docker compose up -d minio createbuckets 后即可真跑。待 CI 接入 MinIO 后可改为必跑。
    """
    parsed = urlparse(settings.s3_endpoint)
    host = parsed.hostname or "localhost"
    port = parsed.port or 9000
    try:
        with socket.create_connection((host, port), timeout=1):
            return
    except OSError:
        pytest.skip(f"对象存储不可达({settings.s3_endpoint})：docker compose up -d minio createbuckets")


def _load_resumes() -> list[dict[str, object]]:
    async def _run() -> list[dict[str, object]]:
        engine = create_async_engine(settings.database_url)
        try:
            async with AsyncSession(engine) as db:
                rows = (await db.execute(select(Resume).order_by(Resume.id))).scalars().all()
                return [
                    {
                        "analyze_status": r.analyze_status,
                        "resume_text": r.resume_text,
                        "filename": r.original_filename,
                    }
                    for r in rows
                ]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _load_knowledge_bases() -> list[dict[str, object]]:
    async def _run() -> list[dict[str, object]]:
        engine = create_async_engine(settings.database_url)
        try:
            async with AsyncSession(engine) as db:
                rows = (await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.id))).scalars().all()
                return [
                    {
                        "vector_status": kb.vector_status,
                        "name": kb.name,
                        "category": kb.category,
                    }
                    for kb in rows
                ]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_resume_upload_persists_and_enqueues_analyze(integration_client: TestClient) -> None:
    """上传简历：真 HTTP -> 真解析 -> 真 S3 -> 真库 insert(analyze_status=PENDING) -> 入队分析。"""
    content = "我的简历：三年 Java 后端开发经验，熟悉 Spring、MySQL、Redis。".encode()
    resp = integration_client.post(
        "/api/resumes/upload",
        files={"file": ("resume.txt", content, "text/plain")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["duplicate"] is False
    assert body["data"]["resume"]["analyzeStatus"] == "PENDING"
    assert body["data"]["storage"]["resumeId"] >= 1

    # 竖切核心：真库落数据
    rows = _load_resumes()
    assert len(rows) == 1
    assert rows[0]["analyze_status"] == "PENDING"  # 待异步分析（消费侧 e2e 覆盖）
    assert rows[0]["filename"] == "resume.txt"
    assert isinstance(rows[0]["resume_text"], str) and rows[0]["resume_text"].strip()  # 解析文本真入库


def test_knowledgebase_upload_persists_and_enqueues_vectorize(integration_client: TestClient) -> None:
    """上传知识库：真 HTTP -> 真解析 -> 真 S3 -> 真库 insert(vector_status=PENDING) -> 入队向量化。"""
    content = "Java 并发编程知识：线程池、synchronized、volatile、AQS。".encode()
    resp = integration_client.post(
        "/api/knowledgebase/upload",
        files={"file": ("kb.txt", content, "text/plain")},
        data={"name": "并发知识库", "category": "Java"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["duplicate"] is False
    assert body["data"]["knowledgeBase"]["vectorStatus"] == "PENDING"

    # 竖切核心：真库落数据
    rows = _load_knowledge_bases()
    assert len(rows) == 1
    assert rows[0]["vector_status"] == "PENDING"  # 待异步向量化（消费侧 e2e 覆盖）
    assert rows[0]["name"] == "并发知识库"
    assert rows[0]["category"] == "Java"
