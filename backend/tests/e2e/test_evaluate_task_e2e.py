"""面试异步评估任务：真实 Redis + Postgres 端到端（#20 AC2：异步评估任务）。

produce(xadd) -> Redis stream -> consume(xreadgroup) -> 评估(假 LLM 图) -> 真库持久化。
仅外部 LLM/评估子图被假化（无法真调 Qwen），Redis 流 + PG 状态机/持久化全真实。
用唯一 stream key 隔离，避免 Redis 残留；Redis 不可用则 skip。
"""

import contextlib
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.entities.evaluation import (
    CategoryScore,
    EvaluationReport,
    QuestionEvaluation,
    ReferenceAnswer,
)
from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.models.interview import InterviewAnswer, InterviewSession
from app.infrastructure.db.repositories.interview_repository import InterviewRepository
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.redis.client import create_redis_client
from app.infrastructure.tasks.constants import STREAM_MAX_LEN, StreamConfig
from app.infrastructure.tasks.interview_evaluate_consumer import EvaluateStreamConsumer


def _questions_json() -> str:
    items = [
        {
            "questionIndex": i,
            "question": f"题{i}",
            "type": "JAVA",
            "category": "Java",
            "topicSummary": f"t{i}",
            "userAnswer": None,
            "score": None,
            "feedback": None,
            "isFollowUp": False,
            "parentQuestionIndex": None,
        }
        for i in range(2)
    ]
    return json.dumps(items, ensure_ascii=False)


def _report(session_id: str) -> EvaluationReport:
    return EvaluationReport(
        session_id=session_id,
        total_questions=2,
        overall_score=80,
        category_scores=[CategoryScore(category="Java", score=80, question_count=2)],
        question_details=[
            QuestionEvaluation(0, "题0", "Java", "答0", 90, "优"),
            QuestionEvaluation(1, "题1", "Java", "答1", 70, "良"),
        ],
        overall_feedback="总评",
        strengths=["扎实"],
        improvements=["补深度"],
        reference_answers=[
            ReferenceAnswer(0, "题0", "参考0", ["要点0"]),
            ReferenceAnswer(1, "题1", "参考1", ["要点1"]),
        ],
    )


async def _seed_session(factory: async_sessionmaker, session_id: str) -> None:
    async with factory() as db:
        db.add(
            InterviewSession(
                session_id=session_id,
                skill_id="java-backend",
                difficulty="mid",
                total_questions=2,
                current_question_index=2,
                status="COMPLETED",
                questions_json=_questions_json(),
                evaluate_status=AsyncTaskStatus.PENDING.value,
            )
        )
        await db.flush()
        sess = (
            await db.execute(select(InterviewSession).where(InterviewSession.session_id == session_id))
        ).scalar_one()
        db.add_all(
            [
                InterviewAnswer(
                    session_id=sess.id, question_index=0, question="题0", category="Java", user_answer="答0"
                ),
                InterviewAnswer(
                    session_id=sess.id, question_index=1, question="题1", category="Java", user_answer="答1"
                ),
            ]
        )
        await db.commit()


async def test_interview_evaluate_task_e2e(live_session_factory: async_sessionmaker) -> None:
    """产 -> Redis 流 -> 消费 -> 假图评估 -> 真库回写答案分数 + 状态机置 COMPLETED。"""
    redis = create_redis_client()
    config = StreamConfig(
        stream_key=f"interview:evaluate:e2e:{uuid.uuid4().hex[:8]}",
        group_name="e2e-group",
        consumer_prefix="e2e-consumer-",
        id_field="sessionId",
    )
    try:
        await redis.create_stream_group(config.stream_key, config.group_name)
    except Exception:
        pytest.skip("Redis 不可用：docker compose up -d redis")

    session_id = f"e2e-{uuid.uuid4().hex[:8]}"
    await _seed_session(live_session_factory, session_id)

    registry = MagicMock()
    registry.get_chat_client = AsyncMock(return_value=MagicMock())
    graph = MagicMock()
    graph.evaluate = AsyncMock(return_value=_report(session_id))
    consumer = EvaluateStreamConsumer(
        redis_client=redis,
        config=config,
        session_factory=live_session_factory,
        repository=InterviewRepository(),
        resume_repository=ResumeRepository(),
        llm_registry=registry,
        evaluation_graph=graph,
    )

    try:
        await redis.xadd(config.stream_key, {config.id_field: session_id, "retryCount": "0"}, max_len=STREAM_MAX_LEN)
        results = await redis.xreadgroup(config.stream_key, config.group_name, "e2e-consumer", count=1, block_ms=2000)
        assert results, "未从 Redis 流读到消息"
        msg_id, data = results[0][1][0]
        await consumer._process_message(msg_id, data)
    finally:
        with contextlib.suppress(Exception):
            await redis.delete(config.stream_key)
        with contextlib.suppress(Exception):
            await redis._redis.aclose()

    async with live_session_factory() as db:
        sess = (
            await db.execute(select(InterviewSession).where(InterviewSession.session_id == session_id))
        ).scalar_one()
        answers = (
            (
                await db.execute(
                    select(InterviewAnswer)
                    .where(InterviewAnswer.session_id == sess.id)
                    .order_by(InterviewAnswer.question_index)
                )
            )
            .scalars()
            .all()
        )

    graph.evaluate.assert_awaited_once()
    assert sess.evaluate_status == AsyncTaskStatus.COMPLETED.value  # 状态机闭环
    assert answers[0].score == 90  # 真库回写逐题分数
    assert answers[1].score == 70
