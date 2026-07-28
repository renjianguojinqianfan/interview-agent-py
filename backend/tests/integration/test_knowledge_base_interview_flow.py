"""知识库组卷面试集成竖切（issue #44，ADR-0016）：插题 -> capacity -> 组卷建会 -> 答题/交卷 -> 评估采用题库参考。

整链：经 API 插题并上架（POST questions + PUT status）-> GET interview-capacity 预检 ->
POST /api/knowledgebase-interviews/sessions 组卷（含容量不足分支）-> 沿用文字面试答题/交卷 ->
评估消费者注入题库参考上下文 + 报告参考答案被题库标准答案覆盖（真库回写）。
仅替身化 AI 边界（评估图假 LLM）；Redis/Postgres 不可用时 CI fail、本地优雅 skip。
"""

import asyncio
import contextlib
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings
from app.domain.entities.evaluation import (
    CategoryScore,
    EvaluationReport,
    QuestionEvaluation,
    ReferenceAnswer,
)
from app.infrastructure.db.models.interview import InterviewAnswer, InterviewSession
from app.infrastructure.db.models.knowledge_base import KnowledgeBase
from app.infrastructure.db.repositories.interview_repository import InterviewRepository
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.redis.client import create_redis_client
from app.infrastructure.tasks.constants import INTERVIEW_EVALUATE
from app.infrastructure.tasks.interview_evaluate_consumer import EvaluateStreamConsumer


def _seed_kb() -> int:
    async def _run() -> int:
        engine = create_async_engine(settings.database_url)
        try:
            async with AsyncSession(engine) as db:
                kb = KnowledgeBase(
                    name="组卷竖切知识库",
                    vector_status="COMPLETED",
                )
                db.add(kb)
                await db.flush()
                kb_id = kb.id  # commit 会过期实体属性，先取 id
                await db.commit()
                return kb_id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _create_active_question(
    client: TestClient, kb_id: int, question: str, reference_answer: str, category: str = "Redis"
) -> None:
    """经 API 插题并上架（覆盖 POST questions + PUT status 竖切债务）。"""
    created = client.post(
        f"/api/knowledgebase/{kb_id}/questions",
        json={
            "category": category,
            "question": question,
            "referenceAnswer": reference_answer,
            "keyPoints": ["要点A"],
            "scoringRubric": "10分制",
            "followUps": [
                {"question": f"{question}-追问1", "referenceAnswer": "追答1", "keyPoints": ["点1"]},
                {"question": f"{question}-追问2", "referenceAnswer": "追答2"},
            ],
        },
    ).json()
    assert created["code"] == 200
    question_id = created["data"]["id"]
    activated = client.put(f"/api/knowledgebase/questions/{question_id}/status", json={"status": "ACTIVE"}).json()
    assert activated["code"] == 200
    assert activated["data"]["status"] == "ACTIVE"


def _load_session_state(session_id: str) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        engine = create_async_engine(settings.database_url)
        try:
            async with AsyncSession(engine) as db:
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
                return {
                    "status": sess.status,
                    "evaluate_status": sess.evaluate_status,
                    "source_type": sess.source_type,
                    "knowledge_base_id": sess.knowledge_base_id,
                    "interview_category": sess.interview_category,
                    "reference_answers_json": sess.reference_answers_json,
                    "answer_references": [(a.question_index, a.reference_answer) for a in answers],
                }
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _evaluate_with_fake_graph(session_id: str, llm_report: EvaluationReport) -> str | None:
    """驱动真评估消费者（假评估图）：返回图收到的 reference_context。"""

    async def _run() -> str | None:
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        redis = create_redis_client()
        try:
            registry = MagicMock()
            registry.get_chat_client = AsyncMock(return_value=MagicMock())
            registry.resolve_provider_id_by_name = AsyncMock(return_value=None)
            graph = MagicMock()
            graph.evaluate = AsyncMock(return_value=llm_report)
            consumer = EvaluateStreamConsumer(
                redis_client=redis,
                config=INTERVIEW_EVALUATE,
                session_factory=factory,
                repository=InterviewRepository(),
                resume_repository=ResumeRepository(),
                llm_registry=registry,
                evaluation_graph=graph,
            )
            data = {b"sessionId": session_id.encode(), b"retryCount": b"0"}
            await consumer._process_message(f"it-{uuid.uuid4().hex[:6]}", data)
            graph.evaluate.assert_awaited_once()
            return graph.evaluate.call_args.kwargs["reference_context"]
        finally:
            with contextlib.suppress(Exception):
                await redis._redis.aclose()
            await engine.dispose()

    return asyncio.run(_run())


def test_knowledge_base_interview_full_flow(integration_client: TestClient) -> None:
    """插题上架 -> capacity -> 不足拒绝 -> 组卷建会 -> 答题/交卷 -> 评估采用题库参考答案。"""
    kb_id = _seed_kb()
    _create_active_question(integration_client, kb_id, "什么是缓存穿透？", "题库参考A")
    _create_active_question(integration_client, kb_id, "什么是缓存击穿？", "题库参考B")

    # 1) 容量预检：方向计数 + 追问档位矩阵（每题 2 个追问 -> 档位 2 可行、档位 3 不可行）
    capacity = integration_client.get(
        f"/api/knowledgebase/{kb_id}/interview-capacity?category=Redis&mainQuestionCount=2"
    ).json()["data"]
    assert capacity["categories"] == [{"category": "Redis", "availableQuestionCount": 2}]
    by_count = {o["followUpCount"]: o for o in capacity["followUpOptions"]}
    assert by_count[2]["selectable"] is True
    assert by_count[3]["availableQuestionCount"] == 0

    # 2) 容量不足：3 道主问题 > 2 道候选，携方向/难度/追问明细拒绝
    insufficient = integration_client.post(
        "/api/knowledgebase-interviews/sessions",
        json={"knowledgeBaseId": kb_id, "category": "Redis", "mainQuestionCount": 3, "followUpCount": 1},
    ).json()
    assert insufficient["code"] == 3012
    assert "方向=Redis" in insufficient["message"]
    assert "难度=mid" in insufficient["message"]

    # 3) 组卷建会：2 主问题 + 每题 1 追问 = 4 题，随题下发题库参考
    created = integration_client.post(
        "/api/knowledgebase-interviews/sessions",
        json={"knowledgeBaseId": kb_id, "category": "Redis", "mainQuestionCount": 2, "followUpCount": 1},
    ).json()
    assert created["code"] == 200
    session_id = created["data"]["sessionId"]
    assert created["data"]["knowledgeBaseId"] == kb_id
    assert created["data"]["interviewCategory"] == "Redis"
    questions = created["data"]["questions"]
    assert len(questions) == 4
    first = questions[0]
    assert first["referenceAnswer"] in {"题库参考A", "题库参考B"}
    follow_ups = [q for q in questions if q["isFollowUp"]]
    assert len(follow_ups) == 2
    assert all(q["parentQuestionIndex"] is not None for q in follow_ups)

    # 4) 会话列表可区分来源
    listed = integration_client.get("/api/interview/sessions").json()["data"]
    assert listed[0]["sourceType"] == "KNOWLEDGE_BASE"
    assert listed[0]["knowledgeBaseId"] == kb_id

    # 5) 沿用既有答题流：取题（CREATED -> IN_PROGRESS）-> 答首题 -> 显式交卷
    q = integration_client.get(f"/api/interview/sessions/{session_id}/question").json()
    assert q["data"]["question"]["questionIndex"] == 0
    answered = integration_client.post(
        f"/api/interview/sessions/{session_id}/answers",
        json={"questionIndex": 0, "answer": "我的回答"},
    ).json()
    assert answered["code"] == 200
    completed = integration_client.post(f"/api/interview/sessions/{session_id}/complete").json()
    assert completed["code"] == 200

    state = _load_session_state(session_id)
    assert state["status"] == "COMPLETED"
    assert state["evaluate_status"] == "PENDING"
    assert state["source_type"] == "KNOWLEDGE_BASE"
    assert state["knowledge_base_id"] == kb_id
    assert state["interview_category"] == "Redis"

    # 6) 评估：题库参考注入上下文 + 报告参考答案以题库标准答案为准
    llm_report = EvaluationReport(
        session_id=session_id,
        total_questions=4,
        overall_score=80,
        category_scores=[CategoryScore(category="Redis", score=80, question_count=1)],
        question_details=[QuestionEvaluation(0, first["question"], "Redis", "我的回答", 80, "尚可")],
        overall_feedback="总评",
        strengths=["熟悉缓存"],
        improvements=["补原理"],
        reference_answers=[ReferenceAnswer(0, first["question"], "LLM参考0", ["LLM要点0"])],
    )
    reference_context = _evaluate_with_fake_graph(session_id, llm_report)

    assert reference_context is not None
    assert first["referenceAnswer"] in reference_context  # 题库参考进入评估上下文

    evaluated = _load_session_state(session_id)
    assert evaluated["evaluate_status"] == "COMPLETED"
    # 报告与逐题回写的参考答案均为题库标准答案（LLM 产出被覆盖）
    assert first["referenceAnswer"] in str(evaluated["reference_answers_json"])
    assert "LLM参考0" not in str(evaluated["reference_answers_json"])
    assert evaluated["answer_references"] == [(0, first["referenceAnswer"])]
