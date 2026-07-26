"""题库异步生成集成竖切（issue #43，ADR-0016）：真 HTTP -> 真库状态机 -> 真 Redis 流 -> 消费落库。

整链：POST generate（真路由/限流/状态机写 QUEUED）-> Redis Stream 真消息 -> 消费者原子领取
（行锁 + taskId 匹配）-> 假 LLM 出题 -> 真库整体替换题库 + COMPLETED -> 轮询/题目列表可见。
仅替身化 AI 边界（embeddings/LLM invoker）；含旧 taskId 串扰静默丢弃用例。
Redis/Postgres 不可用时 CI fail、本地优雅 skip（同 conftest 惯例）。
"""

import asyncio
import contextlib
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.application.knowledgebase.generation_service import (
    GeneratedQuestion,
    GeneratedQuestionList,
    QuestionGenerationService,
)
from app.application.knowledgebase.generation_state_service import QuestionGenerationStateService
from app.config.settings import settings
from app.infrastructure.db.models.knowledge_base import KnowledgeBase, KnowledgeBaseQuestion
from app.infrastructure.db.repositories.knowledge_base_question_repository import KnowledgeBaseQuestionRepository
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.redis.client import create_redis_client
from app.infrastructure.tasks.constants import KB_QUESTION_GEN
from app.infrastructure.tasks.question_gen_consumer import QuestionGenConsumer
from app.infrastructure.tasks.question_gen_producer import QuestionGenProducer
from app.infrastructure.vector.repository import VectorItem, VectorRepository
from tests.integration.conftest import _require_infra_or_skip

_EMBEDDING_DIM = 1024


def _generated_output() -> GeneratedQuestionList:
    return GeneratedQuestionList(
        questions=[
            GeneratedQuestion(category="Redis", question="什么是缓存穿透？", referenceAnswer="参考A"),
            GeneratedQuestion(category="Redis", question="什么是 缓存穿透?", referenceAnswer="归一化后重复"),
            GeneratedQuestion(category="MySQL", question="什么是回表？", referenceAnswer="参考B"),
        ]
    )


def _seed_kb_with_vectors() -> int:
    """种一个已向量化知识库 + 2 条真向量（固定假 embedding，维度 1024）。"""

    async def _run() -> int:
        engine = create_async_engine(settings.database_url)
        try:
            async with AsyncSession(engine) as db:
                kb = KnowledgeBase(
                    file_hash=f"hash-{uuid.uuid4().hex[:8]}",
                    original_filename="guide.md",
                    name="生成竖切知识库",
                    content_text="Redis 与 MySQL 知识",
                    vector_status="COMPLETED",
                )
                db.add(kb)
                await db.flush()
                kb_id = kb.id
                vector_repo = VectorRepository()
                job_id = uuid.uuid4().hex
                items = [
                    VectorItem(content="Redis 缓存穿透是指查询不存在的数据", embedding=[0.1] * _EMBEDDING_DIM),
                    VectorItem(content="MySQL 回表指二级索引回聚簇索引取行", embedding=[0.2] * _EMBEDDING_DIM),
                ]
                await vector_repo.insert_pending(db, job_id, kb_id, items)
                await vector_repo.promote_vector_job(db, kb_id, job_id)
                await db.commit()
                return kb_id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _load_questions(kb_id: int) -> list[dict[str, Any]]:
    async def _run() -> list[dict[str, Any]]:
        engine = create_async_engine(settings.database_url)
        try:
            async with AsyncSession(engine) as db:
                rows = (
                    (
                        await db.execute(
                            select(KnowledgeBaseQuestion)
                            .where(KnowledgeBaseQuestion.knowledge_base_id == kb_id)
                            .order_by(KnowledgeBaseQuestion.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                return [{"question": q.question, "status": q.status, "category": q.category} for q in rows]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _consume(kb_id: int, override_task_id: str | None = None) -> None:
    """从真 Redis 流读一条生成消息并驱动消费者；override_task_id 用于构造旧任务串扰消息。"""

    async def _run() -> None:
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        redis = create_redis_client()
        try:
            state = QuestionGenerationStateService(
                session_factory=factory,
                kb_repository=KnowledgeBaseRepository(),
                question_repository=KnowledgeBaseQuestionRepository(),
            )
            embeddings = MagicMock()
            embeddings.aembed_query = AsyncMock(return_value=[0.1] * _EMBEDDING_DIM)
            registry = MagicMock()
            registry.get_default_embeddings = AsyncMock(return_value=embeddings)
            registry.resolve_provider_id_by_name = AsyncMock(return_value=None)
            registry.get_plain_chat_client = AsyncMock(return_value=MagicMock())
            invoker = MagicMock()
            invoker.invoke = AsyncMock(return_value=_generated_output())
            generation = QuestionGenerationService(
                session_factory=factory,
                kb_repository=KnowledgeBaseRepository(),
                question_repository=KnowledgeBaseQuestionRepository(),
                vector_repository=VectorRepository(),
                llm_registry=registry,
                invoker=invoker,
                state_service=state,
            )
            producer = QuestionGenProducer(redis, KB_QUESTION_GEN, state)
            consumer = QuestionGenConsumer(redis, KB_QUESTION_GEN, state, generation, producer)

            if override_task_id is not None:
                data = {
                    KB_QUESTION_GEN.id_field.encode(): str(kb_id).encode(),
                    b"taskId": override_task_id.encode(),
                    b"retryCount": b"0",
                }
                await consumer._process_message(f"stale-{uuid.uuid4().hex[:6]}", data)
                return

            results = await redis.xreadgroup(
                KB_QUESTION_GEN.stream_key, KB_QUESTION_GEN.group_name, "it-consumer", count=1, block_ms=2000
            )
            assert results, "未从 Redis 流读到题目生成消息"
            msg_id, data = results[0][1][0]
            await consumer._process_message(msg_id, data)
        finally:
            with contextlib.suppress(Exception):
                await redis._redis.aclose()
            await engine.dispose()

    asyncio.run(_run())


def _prepare_stream() -> None:
    """清空生成流并建消费组（隔离历史残留消息）。"""

    async def _run() -> None:
        redis = create_redis_client()
        try:
            with contextlib.suppress(Exception):
                await redis.delete(KB_QUESTION_GEN.stream_key)
            await redis.create_stream_group(KB_QUESTION_GEN.stream_key, KB_QUESTION_GEN.group_name)
        finally:
            with contextlib.suppress(Exception):
                await redis._redis.aclose()

    try:
        asyncio.run(_run())
    except Exception:
        _require_infra_or_skip("Redis 不可用：docker compose up -d redis")


def test_question_generation_full_flow(integration_client: TestClient) -> None:
    """提交 -> 原子领取 -> 假 LLM -> 归一化去重 -> 整体替换落库 -> COMPLETED -> 轮询与列表可见。"""
    _prepare_stream()
    kb_id = _seed_kb_with_vectors()

    resp = integration_client.post(
        f"/api/knowledgebase/{kb_id}/questions/generate",
        json={"questionCount": 3, "followUpCount": 1, "categoryLimit": 3},
    )
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["questionGenStatus"] == "QUEUED"
    task_id = body["data"]["questionGenTaskId"]
    assert task_id

    # 进行中重复提交被拒（QUEUED 属 active）
    dup = integration_client.post(
        f"/api/knowledgebase/{kb_id}/questions/generate",
        json={"questionCount": 3, "categoryLimit": 3},
    )
    assert dup.json()["code"] == 400
    assert "请勿重复提交" in dup.json()["message"]

    _consume(kb_id)

    status = integration_client.get(f"/api/knowledgebase/{kb_id}/questions/generation-status").json()["data"]
    assert status["questionGenStatus"] == "COMPLETED"
    assert status["questionGenTaskId"] == task_id
    assert status["savedCount"] == 2
    assert status["skippedCount"] == 1
    assert status["message"] == "已生成 2 道题，跳过 1 道重复题"

    questions = _load_questions(kb_id)
    assert [q["question"] for q in questions] == ["什么是缓存穿透？", "什么是回表？"]
    assert all(q["status"] == "DRAFT" for q in questions)

    listed = integration_client.get(f"/api/knowledgebase/{kb_id}/questions").json()["data"]
    assert len(listed) == 2


def test_stale_task_id_message_discarded(integration_client: TestClient) -> None:
    """旧 taskId 消息串扰：原子领取失败 -> 静默 ACK 丢弃，不落库、不改状态。"""
    _prepare_stream()
    kb_id = _seed_kb_with_vectors()

    first = integration_client.post(
        f"/api/knowledgebase/{kb_id}/questions/generate",
        json={"questionCount": 3, "categoryLimit": 3},
    )
    assert first.json()["code"] == 200

    # 用一个已失效的 taskId 构造串扰消息（当前任务 taskId 不同）
    _consume(kb_id, override_task_id=f"stale-{uuid.uuid4().hex[:8]}")

    status = integration_client.get(f"/api/knowledgebase/{kb_id}/questions/generation-status").json()["data"]
    assert status["questionGenStatus"] == "QUEUED"  # 状态未被串扰消息推进
    assert _load_questions(kb_id) == []  # 未落库

    # 真消息（当前 taskId）仍可正常消费闭环
    _consume(kb_id)
    status = integration_client.get(f"/api/knowledgebase/{kb_id}/questions/generation-status").json()["data"]
    assert status["questionGenStatus"] == "COMPLETED"
