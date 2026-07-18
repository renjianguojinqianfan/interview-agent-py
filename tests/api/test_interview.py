"""文字面试 API 路由测试。"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_interview_session_service
from app.api.rate_limit import limiter
from app.application.interview.schemas import (
    CurrentQuestionResponse,
    InterviewQuestionDTO,
    InterviewSessionDTO,
    SessionListItemDTO,
    SessionPageDTO,
    SubmitAnswerResponse,
)
from app.domain.errors import BusinessException, ErrorCode
from app.main import app

client = TestClient(app)


def _session_dto(session_id: str = "sess123") -> InterviewSessionDTO:
    return InterviewSessionDTO(
        sessionId=session_id,
        resumeText="",
        totalQuestions=3,
        currentQuestionIndex=0,
        questions=[
            InterviewQuestionDTO(
                questionIndex=i,
                question=f"Q{i}",
                type="JAVA",
                category="Java",
            )
            for i in range(3)
        ],
        status="CREATED",
    )


def _mock_service() -> MagicMock:
    service = MagicMock()
    service.create_session = AsyncMock()
    service.get_session = AsyncMock()
    service.get_current_question = AsyncMock()
    service.submit_answer = AsyncMock()
    service.save_answer = AsyncMock()
    service.complete_interview = AsyncMock()
    service.find_unfinished_session = AsyncMock()
    service.list_sessions = AsyncMock()
    service.delete_session = AsyncMock()
    return service


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def mock_service() -> Iterator[MagicMock]:
    service = _mock_service()
    app.dependency_overrides[get_interview_session_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_interview_session_service, None)


class TestCreateSession:
    def test_creates_session(self, mock_service: MagicMock) -> None:
        mock_service.create_session.return_value = _session_dto()
        resp = client.post(
            "/api/interview/sessions",
            json={"questionCount": 3, "skillId": "java-backend"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["sessionId"] == "sess123"
        assert body["data"]["totalQuestions"] == 3

    def test_validates_question_count_min(self, mock_service: MagicMock) -> None:
        resp = client.post(
            "/api/interview/sessions",
            json={"questionCount": 2, "skillId": "java-backend"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 400

    def test_validates_question_count_max(self, mock_service: MagicMock) -> None:
        resp = client.post(
            "/api/interview/sessions",
            json={"questionCount": 21, "skillId": "java-backend"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 400

    def test_requires_skill_id(self, mock_service: MagicMock) -> None:
        resp = client.post("/api/interview/sessions", json={"questionCount": 3})
        assert resp.status_code == 200
        assert resp.json()["code"] == 400


class TestListSessions:
    def test_returns_paginated(self, mock_service: MagicMock) -> None:
        mock_service.list_sessions.return_value = SessionPageDTO(
            items=[
                SessionListItemDTO(
                    sessionId="s1",
                    skillId="java-backend",
                    difficulty="mid",
                    totalQuestions=3,
                    currentQuestionIndex=3,
                    status="COMPLETED",
                )
            ],
            total=1,
            page=1,
            size=10,
        )
        resp = client.get("/api/interview/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["sessionId"] == "s1"


class TestGetSession:
    def test_returns_session(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = _session_dto()
        resp = client.get("/api/interview/sessions/sess123")
        assert resp.status_code == 200
        assert resp.json()["data"]["sessionId"] == "sess123"

    def test_not_found_returns_200_with_error_code(self, mock_service: MagicMock) -> None:
        mock_service.get_session.side_effect = BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND)
        resp = client.get("/api/interview/sessions/missing")
        assert resp.status_code == 200
        assert resp.json()["code"] == ErrorCode.INTERVIEW_SESSION_NOT_FOUND.code


class TestGetCurrentQuestion:
    def test_returns_current_question(self, mock_service: MagicMock) -> None:
        mock_service.get_current_question.return_value = CurrentQuestionResponse(
            completed=False,
            question=InterviewQuestionDTO(
                questionIndex=0,
                question="Q0",
                type="JAVA",
                category="Java",
            ),
        )
        resp = client.get("/api/interview/sessions/sess123/question")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["completed"] is False
        assert body["question"]["questionIndex"] == 0

    def test_returns_completed(self, mock_service: MagicMock) -> None:
        mock_service.get_current_question.return_value = CurrentQuestionResponse(
            completed=True,
            message="所有问题已回答完毕",
        )
        resp = client.get("/api/interview/sessions/sess123/question")
        assert resp.json()["data"]["completed"] is True


class TestSubmitAnswer:
    def test_submits_answer(self, mock_service: MagicMock) -> None:
        mock_service.submit_answer.return_value = SubmitAnswerResponse(
            hasNextQuestion=True,
            nextQuestion=InterviewQuestionDTO(
                questionIndex=1,
                question="Q1",
                type="JAVA",
                category="Java",
            ),
            currentIndex=1,
            totalQuestions=3,
        )
        resp = client.post(
            "/api/interview/sessions/sess123/answers",
            json={"questionIndex": 0, "answer": "answer0"},
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["hasNextQuestion"] is True
        assert body["currentIndex"] == 1

    def test_validates_answer_not_empty(self, mock_service: MagicMock) -> None:
        resp = client.post(
            "/api/interview/sessions/sess123/answers",
            json={"questionIndex": 0, "answer": ""},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 400


class TestSaveAnswer:
    def test_saves_answer(self, mock_service: MagicMock) -> None:
        mock_service.save_answer.return_value = None
        resp = client.put(
            "/api/interview/sessions/sess123/answers",
            json={"questionIndex": 0, "answer": "draft"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 200


class TestCompleteInterview:
    def test_completes(self, mock_service: MagicMock) -> None:
        mock_service.complete_interview.return_value = None
        resp = client.post("/api/interview/sessions/sess123/complete")
        assert resp.status_code == 200

    def test_already_completed_returns_error_code(self, mock_service: MagicMock) -> None:
        mock_service.complete_interview.side_effect = BusinessException(ErrorCode.INTERVIEW_ALREADY_COMPLETED)
        resp = client.post("/api/interview/sessions/sess123/complete")
        assert resp.json()["code"] == ErrorCode.INTERVIEW_ALREADY_COMPLETED.code


class TestFindUnfinishedSession:
    def test_returns_unfinished(self, mock_service: MagicMock) -> None:
        mock_service.find_unfinished_session.return_value = _session_dto("existing")
        resp = client.get("/api/interview/sessions/unfinished/42")
        assert resp.status_code == 200
        assert resp.json()["data"]["sessionId"] == "existing"


class TestDeleteSession:
    def test_deletes(self, mock_service: MagicMock) -> None:
        mock_service.delete_session.return_value = None
        resp = client.delete("/api/interview/sessions/sess123")
        assert resp.status_code == 200
        assert resp.json()["code"] == 200
