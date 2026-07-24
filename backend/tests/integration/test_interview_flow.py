"""文字面试核心流集成竖切（ADR-0016）：真 HTTP -> 真服务 -> 真库，仅假出题 LLM。

覆盖"开始面试 -> 取题 -> 逐题作答 -> 末题触发交卷"整链，断言真库落数据（会话状态机置
COMPLETED + evaluate_status=PENDING、逐题答案文本入库）—— 分层单测（api mock 服务 /
application mock 仓储）各自为政，无法证明此链拼通；此竖切正是 ADR-0016 要补的"按钮 -> 数据"。
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.application.interview.question_service import QuestionService
from app.config.settings import settings
from app.domain.entities.interview import InterviewQuestion
from app.infrastructure.db.models.interview import InterviewAnswer, InterviewSession


async def _fake_generate(
    self: QuestionService,
    *,
    question_count: int,
    **kwargs: object,
) -> list[InterviewQuestion]:
    """假出题：不调 LLM（AI 边界的唯一替身），按数量返回固定题目，其余链路全真。"""
    return [
        InterviewQuestion(question_index=i, question=f"Q{i}", type="JAVA", category="Java", topic_summary=f"t{i}")
        for i in range(question_count)
    ]


def _load_state(session_id: str) -> dict[str, object]:
    """用独立 engine/事件循环从真库读回会话状态与答案（取原始值，规避 detached 实例惰性加载）。"""

    async def _run() -> dict[str, object]:
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
                    "answers": [(a.question_index, a.user_answer) for a in answers],
                }
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_interview_full_flow_persists_to_real_db(
    integration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开始面试 -> 取题 -> 逐题作答 -> 末题交卷；断言真库状态机 + 逐题答案 + 评估入队 PENDING。"""
    monkeypatch.setattr(QuestionService, "generate", _fake_generate)

    # 1) 开始面试：真 HTTP -> 真服务（假出题）-> 真库 insert，返回 Result 包裹 + 题目
    resp = integration_client.post(
        "/api/interview/sessions",
        json={"questionCount": 3, "skillId": "java-backend"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    session_id = body["data"]["sessionId"]
    assert body["data"]["totalQuestions"] == 3
    assert len(body["data"]["questions"]) == 3

    # 2) 取当前问题：状态机 CREATED -> IN_PROGRESS（真库更新）
    q = integration_client.get(f"/api/interview/sessions/{session_id}/question").json()
    assert q["code"] == 200
    assert q["data"]["completed"] is False
    assert q["data"]["question"]["questionIndex"] == 0

    # 3) 逐题作答；末题（index=2）触发交卷 + 评估入队
    for i in range(3):
        r = integration_client.post(
            f"/api/interview/sessions/{session_id}/answers",
            json={"questionIndex": i, "answer": f"答{i}"},
        ).json()
        assert r["code"] == 200
        assert r["data"]["hasNextQuestion"] is (i < 2)

    # 4) 竖切核心断言：真库落数据（按钮 -> 数据）
    state = _load_state(session_id)
    assert state["status"] == "COMPLETED"  # 状态机闭环
    assert state["evaluate_status"] == "PENDING"  # 交卷同事务置 PENDING，事务后入队评估
    assert state["answers"] == [(0, "答0"), (1, "答1"), (2, "答2")]  # 逐题答案真库回写
