"""语音面试"结束 -> 评估入队"集成竖切（ADR-0016）：真 HTTP -> 真服务 -> 真库 + 真 Redis 入队。

覆盖"创建语音会话 -> 结束会话"整链，断言真库状态机置 COMPLETED + evaluate_status=PENDING（同事务置
PENDING、事务后入队语音评估），并经读侧评估端点回读 PENDING。创建时 llm_provider 缺省(None) 走真实
"无供应商即回退 None"路径（不触 DB provider 查询），故全程无需 AI 替身 —— 分层单测（api mock 服务）
证明不了状态机与入队真的拼通，此竖切正是 ADR-0016 要补的"按钮 -> 数据"。
"""

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import settings
from app.infrastructure.db.models.voice_interview import VoiceInterviewSession


def _load_session(session_pk: int) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        engine = create_async_engine(settings.database_url)
        try:
            async with AsyncSession(engine) as db:
                orm = (
                    await db.execute(select(VoiceInterviewSession).where(VoiceInterviewSession.id == session_pk))
                ).scalar_one()
                return {
                    "status": orm.status,
                    "evaluate_status": orm.evaluate_status,
                    "end_time_set": orm.end_time is not None,
                    "actual_duration_set": orm.actual_duration is not None,
                }
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_voice_end_session_transitions_and_enqueues_evaluate(integration_client: TestClient) -> None:
    """创建语音会话 -> 结束；断言真库 COMPLETED + evaluate_status=PENDING + 读侧回读 PENDING。"""
    # 1) 创建：llm_provider 缺省 -> resolve 回退 None（无需真实供应商）；真库 insert(status=IN_PROGRESS)
    create = integration_client.post("/api/voice-interview/sessions", json={"skillId": "java-backend"})
    assert create.status_code == 200
    body = create.json()
    assert body["code"] == 200
    session_pk = body["data"]["id"]
    assert body["data"]["status"] == "IN_PROGRESS"

    # 2) 结束：状态机 IN_PROGRESS -> COMPLETED，同事务置 evaluate_status=PENDING，事务后入队语音评估
    end = integration_client.post(f"/api/voice-interview/sessions/{session_pk}/end")
    assert end.status_code == 200
    assert end.json()["code"] == 200

    # 3) 竖切核心：真库落数据（按钮 -> 数据）
    state = _load_session(session_pk)
    assert state["status"] == "COMPLETED"  # 状态机闭环
    assert state["evaluate_status"] == "PENDING"  # 入队评估（消费侧 e2e 覆盖）
    assert state["end_time_set"] is True
    assert state["actual_duration_set"] is True

    # 4) 读侧 HTTP 也回读 PENDING（真实评估读服务，证明写侧对读侧可见）
    status = integration_client.get(f"/api/voice-interview/sessions/{session_pk}/evaluation").json()
    assert status["code"] == 200
    assert status["data"]["evaluateStatus"] == "PENDING"


def test_voice_pause_resume_resume_is_idempotent(integration_client: TestClient) -> None:
    """#60 竖切：create -> pause -> resume(200) -> resume(200 幂等)。

    修复前首次 resume 在 commit 后读服务端 onupdate 的 updated_at 触发 MissingGreenlet 500，
    留下 DB 已 IN_PROGRESS 的中间态；重试被状态机以非法迁移拒绝。本用例直接编码验收标准：
    两次 resume 均 200 且返回完整 DTO（含 updatedAt），最终真库状态 IN_PROGRESS。
    """
    create = integration_client.post("/api/voice-interview/sessions", json={"skillId": "java-backend"})
    assert create.status_code == 200
    session_pk = create.json()["data"]["id"]

    pause = integration_client.put(
        f"/api/voice-interview/sessions/{session_pk}/pause", json={"reason": "user_initiated"}
    )
    assert pause.json()["code"] == 200

    # 首次 resume：修复前此处 500（MissingGreenlet）
    resume1 = integration_client.put(f"/api/voice-interview/sessions/{session_pk}/resume").json()
    assert resume1["code"] == 200
    assert resume1["data"]["status"] == "IN_PROGRESS"
    assert resume1["data"]["updatedAt"]  # commit 后 onupdate 列可读（eager_defaults 回归防护）
    assert resume1["data"]["webSocketUrl"]

    # 重复 resume：幂等成功（修复前报非法状态迁移 400）
    resume2 = integration_client.put(f"/api/voice-interview/sessions/{session_pk}/resume").json()
    assert resume2["code"] == 200
    assert resume2["data"]["status"] == "IN_PROGRESS"
    assert resume2["data"]["webSocketUrl"]

    state = _load_session(session_pk)
    assert state["status"] == "IN_PROGRESS"
