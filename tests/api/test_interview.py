"""文字面试 API 路由测试。"""

from collections.abc import Iterator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_interview_evaluation_service, get_interview_session_service
from app.api.rate_limit import limiter
from app.application.interview.schemas import (
    AnswerItemDTO,
    CategoryScoreDTO,
    CurrentQuestionResponse,
    EvaluationResultDTO,
    InterviewDetailDTO,
    InterviewQuestionDTO,
    InterviewSessionDTO,
    QuestionEvaluationDetailDTO,
    ReferenceAnswerDTO,
    SessionListItemDTO,
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

    def test_accepts_force_create_and_resume_text(self, mock_service: MagicMock) -> None:
        """#28 契约：forceCreate + resumeText 被接收并传入服务（非静默丢弃）。"""
        mock_service.create_session.return_value = _session_dto()
        resp = client.post(
            "/api/interview/sessions",
            json={
                "questionCount": 3,
                "skillId": "java-backend",
                "forceCreate": True,
                "resumeText": "纯文本简历",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 200
        req = mock_service.create_session.await_args.args[0]
        assert req.force_create is True
        assert req.resume_text == "纯文本简历"


class TestListSessions:
    def test_returns_bare_array_with_contract_fields(self, mock_service: MagicMock) -> None:
        mock_service.list_sessions.return_value = [
            SessionListItemDTO(
                sessionId="s1",
                skillId="java-backend",
                difficulty="mid",
                resumeId=7,
                totalQuestions=3,
                status="EVALUATED",
                evaluateStatus="COMPLETED",
                evaluateError=None,
                overallScore=82,
                createdAt=datetime(2026, 7, 18, 10, 0, 0),
                completedAt=datetime(2026, 7, 18, 10, 30, 0),
            )
        ]
        resp = client.get("/api/interview/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["data"], list)
        assert body["data"][0]["sessionId"] == "s1"
        assert body["data"][0]["resumeId"] == 7
        assert body["data"][0]["evaluateStatus"] == "COMPLETED"
        assert body["data"][0]["overallScore"] == 82
        assert body["data"][0]["createdAt"] == "2026-07-18T10:00:00"

    def test_calls_service_without_pagination(self, mock_service: MagicMock) -> None:
        mock_service.list_sessions.return_value = []
        client.get("/api/interview/sessions")
        mock_service.list_sessions.assert_awaited_once_with()


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


def _evaluation_dto() -> EvaluationResultDTO:
    return EvaluationResultDTO(
        sessionId="sess123",
        totalQuestions=2,
        overallScore=80,
        overallFeedback="整体良好",
        categoryScores=[CategoryScoreDTO(category="Java", score=80, questionCount=2)],
        questionDetails=[
            QuestionEvaluationDetailDTO(
                questionIndex=0, question="Q1", category="Java", userAnswer="A1", score=90, feedback="优"
            ),
            QuestionEvaluationDetailDTO(
                questionIndex=1, question="Q2", category="Java", userAnswer="A2", score=70, feedback="良"
            ),
        ],
        strengths=["基础扎实"],
        improvements=["需补深度"],
        referenceAnswers=[
            ReferenceAnswerDTO(questionIndex=0, question="Q1", referenceAnswer="参考1", keyPoints=["要点1"])
        ],
        evaluateStatus="COMPLETED",
    )


def _mock_eval_service() -> MagicMock:
    service = MagicMock()
    service.get_evaluation = AsyncMock()
    service.get_detail = AsyncMock()
    service.export_report = AsyncMock()
    return service


@pytest.fixture()
def mock_eval_service() -> Iterator[MagicMock]:
    service = _mock_eval_service()
    app.dependency_overrides[get_interview_evaluation_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_interview_evaluation_service, None)


class TestGetEvaluation:
    def test_returns_evaluation(self, mock_eval_service: MagicMock) -> None:
        mock_eval_service.get_evaluation.return_value = _evaluation_dto()
        resp = client.get("/api/interview/sessions/sess123/evaluation")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["overallScore"] == 80
        assert body["data"]["questionDetails"][0]["score"] == 90
        assert body["data"]["referenceAnswers"][0]["keyPoints"] == ["要点1"]

    def test_not_evaluated_returns_error_code(self, mock_eval_service: MagicMock) -> None:
        mock_eval_service.get_evaluation.side_effect = BusinessException(ErrorCode.INTERVIEW_EVALUATION_NOT_FOUND)
        resp = client.get("/api/interview/sessions/sess123/evaluation")
        assert resp.status_code == 200
        assert resp.json()["code"] == ErrorCode.INTERVIEW_EVALUATION_NOT_FOUND.code


def _detail_dto() -> InterviewDetailDTO:
    now = datetime(2026, 7, 20, 9, 0, 0)
    return InterviewDetailDTO(
        id=1,
        sessionId="sess123",
        totalQuestions=2,
        status="EVALUATED",
        evaluateStatus="COMPLETED",
        evaluateError=None,
        overallScore=80,
        overallFeedback="整体良好",
        createdAt=now,
        completedAt=now,
        strengths=["基础扎实"],
        improvements=["需补深度"],
        referenceAnswers=[
            ReferenceAnswerDTO(questionIndex=0, question="Q1", referenceAnswer="参考1", keyPoints=["要点1"])
        ],
        answers=[
            AnswerItemDTO(
                questionIndex=0,
                question="Q1",
                category="Java",
                userAnswer="A1",
                score=90,
                feedback="优",
                referenceAnswer="参考1",
                keyPoints=["要点1"],
                answeredAt=now,
            ),
            AnswerItemDTO(
                questionIndex=1,
                question="Q2",
                category="Java",
                userAnswer="A2",
                score=70,
                feedback="良",
                answeredAt=now,
            ),
        ],
    )


class TestGetDetail:
    def test_returns_detail_with_camelcase_answers(self, mock_eval_service: MagicMock) -> None:
        mock_eval_service.get_detail.return_value = _detail_dto()
        resp = client.get("/api/interview/sessions/sess123/details")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        data = body["data"]
        # 裸对象（非分页包装）+ camelCase
        assert data["id"] == 1
        assert data["sessionId"] == "sess123"
        assert data["createdAt"]
        assert len(data["answers"]) == 2
        assert data["answers"][0]["questionIndex"] == 0
        assert data["answers"][0]["answeredAt"]
        assert data["answers"][0]["referenceAnswer"] == "参考1"
        assert data["answers"][0]["keyPoints"] == ["要点1"]

    def test_session_missing_returns_3001(self, mock_eval_service: MagicMock) -> None:
        mock_eval_service.get_detail.side_effect = BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND)
        resp = client.get("/api/interview/sessions/missing/details")
        assert resp.status_code == 200
        assert resp.json()["code"] == ErrorCode.INTERVIEW_SESSION_NOT_FOUND.code


class TestExportReport:
    def test_returns_pdf(self, mock_eval_service: MagicMock) -> None:
        mock_eval_service.export_report.return_value = b"%PDF-1.4 fake"
        resp = client.get("/api/interview/sessions/sess123/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert b"%PDF-1.4 fake" in resp.content
        assert "attachment" in resp.headers["content-disposition"]

    def test_not_evaluated_returns_error_code(self, mock_eval_service: MagicMock) -> None:
        mock_eval_service.export_report.side_effect = BusinessException(ErrorCode.INTERVIEW_EVALUATION_NOT_FOUND)
        resp = client.get("/api/interview/sessions/sess123/export")
        assert resp.json()["code"] == ErrorCode.INTERVIEW_EVALUATION_NOT_FOUND.code
