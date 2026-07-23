"""语音面试 REST 接口测试：API 层接缝，mock 应用服务。"""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_voice_evaluation_service, get_voice_session_service
from app.application.voice.schemas import (
    VoiceAnswerDetailDTO,
    VoiceEvaluationDetailDTO,
    VoiceEvaluationStatusDTO,
    VoiceMessageDTO,
    VoiceSessionDTO,
    VoiceSessionMetaDTO,
)
from app.domain.errors import BusinessException, ErrorCode
from app.main import app

client = TestClient(app)


def _session_dto(session_id: int = 1, status: str = "IN_PROGRESS") -> VoiceSessionDTO:
    now = datetime(2026, 7, 21, 10, 0, 0)
    return VoiceSessionDTO(
        id=session_id,
        session_id=session_id,
        user_id="default",
        role_type="Java面试官",
        skill_id="java-backend",
        difficulty="mid",
        custom_jd_text=None,
        resume_id=None,
        intro_enabled=True,
        tech_enabled=True,
        project_enabled=True,
        hr_enabled=True,
        llm_provider=None,
        current_phase="INTRO",
        status=status,
        planned_duration=30,
        actual_duration=None,
        start_time=now,
        end_time=None,
        created_at=now,
        updated_at=now,
        paused_at=None,
        resumed_at=None,
        evaluate_status=None,
    )


def _meta_dto(session_id: int = 1) -> VoiceSessionMetaDTO:
    now = datetime(2026, 7, 21, 10, 0, 0)
    return VoiceSessionMetaDTO(
        id=session_id,
        session_id=session_id,
        role_type="Java面试官",
        skill_id="java-backend",
        status="IN_PROGRESS",
        current_phase="INTRO",
        start_time=now,
        end_time=None,
        created_at=now,
        updated_at=now,
        actual_duration=120,
        message_count=6,
        evaluate_status=None,
        evaluate_error=None,
    )


def _message_dto(msg_id: int = 1, seq: int = 1) -> VoiceMessageDTO:
    return VoiceMessageDTO(
        id=msg_id,
        session_id=1,
        message_type="DIALOGUE",
        phase="TECH",
        user_recognized_text="用户回答",
        ai_generated_text="AI 提问",
        timestamp=datetime(2026, 7, 21, 10, 1, 0),
        sequence_num=seq,
    )


def _eval_status_dto(status: str = "COMPLETED", evaluate_error: str | None = None) -> VoiceEvaluationStatusDTO:
    detail = None
    if status == "COMPLETED":
        detail = VoiceEvaluationDetailDTO(
            session_id=1,
            total_questions=1,
            overall_score=85,
            overall_feedback="整体表现良好",
            strengths=["基础扎实"],
            improvements=["需加强系统设计"],
            answers=[
                VoiceAnswerDetailDTO(
                    question_index=0,
                    question="Q0",
                    category="Java",
                    user_answer="A0",
                    score=90,
                    feedback="好",
                    reference_answer="参考0",
                    key_points=["要点0"],
                )
            ],
        )
    return VoiceEvaluationStatusDTO(evaluate_status=status, evaluate_error=evaluate_error, evaluation=detail)


def _create_body() -> dict:
    return {
        "roleType": "Java面试官",
        "skillId": "java-backend",
        "difficulty": "mid",
        "introEnabled": True,
        "techEnabled": True,
        "projectEnabled": True,
        "hrEnabled": True,
        "plannedDuration": 30,
    }


def _override_services(mock_session: AsyncMock, mock_eval: AsyncMock) -> None:
    app.dependency_overrides[get_voice_session_service] = lambda: mock_session
    app.dependency_overrides[get_voice_evaluation_service] = lambda: mock_eval


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


class TestCreateSession:
    def test_create_returns_session(self) -> None:
        mock = AsyncMock()
        mock.create_session.return_value = _session_dto(1)
        _override_services(mock, AsyncMock())

        resp = client.post("/api/voice-interview/sessions", json=_create_body())

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["id"] == 1
        assert body["data"]["sessionId"] == 1
        assert body["data"]["webSocketUrl"].endswith("/ws/voice-interview/1")
        assert body["data"]["status"] == "IN_PROGRESS"
        assert body["data"]["currentPhase"] == "INTRO"
        mock.create_session.assert_awaited_once()


class TestGetSession:
    def test_get_returns_session(self) -> None:
        mock = AsyncMock()
        mock.get_session.return_value = _session_dto(2, "PAUSED")
        _override_services(mock, AsyncMock())

        resp = client.get("/api/voice-interview/sessions/2")

        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == 2
        assert resp.json()["data"]["sessionId"] == 2
        assert resp.json()["data"]["webSocketUrl"].endswith("/ws/voice-interview/2")
        assert resp.json()["data"]["status"] == "PAUSED"
        mock.get_session.assert_awaited_once()

    def test_get_not_found(self) -> None:
        mock = AsyncMock()
        mock.get_session.side_effect = BusinessException(ErrorCode.VOICE_SESSION_NOT_FOUND, "会话不存在: 99")
        _override_services(mock, AsyncMock())

        resp = client.get("/api/voice-interview/sessions/99")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 10001
        assert body["data"] is None


class TestEndSession:
    def test_end_returns_success(self) -> None:
        mock = AsyncMock()
        mock.end_session.return_value = None
        _override_services(mock, AsyncMock())

        resp = client.post("/api/voice-interview/sessions/1/end")

        assert resp.status_code == 200
        assert resp.json()["code"] == 200
        mock.end_session.assert_awaited_once()

    def test_end_already_completed_raises(self) -> None:
        mock = AsyncMock()
        mock.end_session.side_effect = BusinessException(ErrorCode.BAD_REQUEST, "非法状态迁移")
        _override_services(mock, AsyncMock())

        resp = client.post("/api/voice-interview/sessions/1/end")

        assert resp.json()["code"] == 400


class TestPauseSession:
    def test_pause_returns_success(self) -> None:
        mock = AsyncMock()
        mock.pause_session.return_value = None
        _override_services(mock, AsyncMock())

        resp = client.put("/api/voice-interview/sessions/1/pause", json={"reason": "user_initiated"})

        assert resp.status_code == 200
        assert resp.json()["code"] == 200
        mock.pause_session.assert_awaited_once()


class TestResumeSession:
    def test_resume_returns_session(self) -> None:
        mock = AsyncMock()
        mock.resume_session.return_value = _session_dto(1, "IN_PROGRESS")
        _override_services(mock, AsyncMock())

        resp = client.put("/api/voice-interview/sessions/1/resume")

        assert resp.status_code == 200
        assert resp.json()["data"]["sessionId"] == 1
        assert resp.json()["data"]["webSocketUrl"].endswith("/ws/voice-interview/1")
        assert resp.json()["data"]["status"] == "IN_PROGRESS"


class TestListSessions:
    def test_list_returns_metas(self) -> None:
        mock = AsyncMock()
        mock.list_sessions.return_value = [_meta_dto(1), _meta_dto(2)]
        _override_services(mock, AsyncMock())

        resp = client.get("/api/voice-interview/sessions", params={"status": "IN_PROGRESS"})

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[0]["sessionId"] == 1
        # #27 列表元数据对齐（camelCase）：修复 Invalid Date / 排序
        assert data[0]["createdAt"]
        assert data[0]["messageCount"] == 6
        assert data[0]["actualDuration"] == 120
        assert "evaluateError" in data[0]

    def test_list_no_filters(self) -> None:
        mock = AsyncMock()
        mock.list_sessions.return_value = []
        _override_services(mock, AsyncMock())

        resp = client.get("/api/voice-interview/sessions")

        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestDeleteSession:
    def test_delete_returns_success(self) -> None:
        mock = AsyncMock()
        mock.delete_session.return_value = None
        _override_services(mock, AsyncMock())

        resp = client.delete("/api/voice-interview/sessions/1")

        assert resp.status_code == 200
        assert resp.json()["code"] == 200
        mock.delete_session.assert_awaited_once()


class TestGetMessages:
    def test_messages_returned(self) -> None:
        mock = AsyncMock()
        mock.get_messages.return_value = [_message_dto(1, 1), _message_dto(2, 2)]
        _override_services(mock, AsyncMock())

        resp = client.get("/api/voice-interview/sessions/1/messages")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2
        assert data[0]["aiGeneratedText"] == "AI 提问"
        assert data[1]["sequenceNum"] == 2


class TestGetEvaluation:
    def test_get_completed_with_detail(self) -> None:
        mock_eval = AsyncMock()
        mock_eval.get_evaluation.return_value = _eval_status_dto("COMPLETED")
        _override_services(AsyncMock(), mock_eval)

        resp = client.get("/api/voice-interview/sessions/1/evaluation")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["evaluateStatus"] == "COMPLETED"
        assert data["evaluation"]["sessionId"] == 1
        assert data["evaluation"]["totalQuestions"] == 1
        assert data["evaluation"]["overallScore"] == 85
        assert data["evaluation"]["strengths"] == ["基础扎实"]
        # 扁平 answers[]（修复前端 evaluation.answers.map() 崩溃）+ camelCase
        answers = data["evaluation"]["answers"]
        assert len(answers) == 1
        assert answers[0]["questionIndex"] == 0
        assert answers[0]["userAnswer"] == "A0"
        assert answers[0]["referenceAnswer"] == "参考0"
        assert answers[0]["keyPoints"] == ["要点0"]
        # 旧三段式字段已下线
        assert "categoryScores" not in data["evaluation"]
        assert "questionDetails" not in data["evaluation"]

    def test_get_pending_without_detail(self) -> None:
        mock_eval = AsyncMock()
        mock_eval.get_evaluation.return_value = _eval_status_dto("PENDING")
        _override_services(AsyncMock(), mock_eval)

        resp = client.get("/api/voice-interview/sessions/1/evaluation")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["evaluateStatus"] == "PENDING"
        assert data["evaluation"] is None

    def test_get_failed_exposes_evaluate_error(self) -> None:
        mock_eval = AsyncMock()
        mock_eval.get_evaluation.return_value = _eval_status_dto("FAILED", evaluate_error="评估超时")
        _override_services(AsyncMock(), mock_eval)

        resp = client.get("/api/voice-interview/sessions/1/evaluation")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["evaluateStatus"] == "FAILED"
        assert data["evaluateError"] == "评估超时"
        assert data["evaluation"] is None


class TestTriggerEvaluation:
    def test_trigger_returns_pending(self) -> None:
        mock = AsyncMock()
        mock.trigger_evaluation.return_value = _eval_status_dto("PENDING")
        _override_services(mock, AsyncMock())

        resp = client.post("/api/voice-interview/sessions/1/evaluation")

        assert resp.status_code == 200
        assert resp.json()["data"]["evaluateStatus"] == "PENDING"
        mock.trigger_evaluation.assert_awaited_once()
