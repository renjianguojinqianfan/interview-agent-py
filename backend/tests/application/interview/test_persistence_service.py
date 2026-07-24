"""InterviewPersistenceService 单元测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.interview.persistence_service import InterviewPersistenceService
from app.domain.entities.interview import InterviewQuestion, SessionStatus
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.question_codec import deserialize_questions, serialize_questions
from app.infrastructure.db.models.interview import InterviewAnswer as InterviewAnswerORM
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    return mock


@pytest.fixture()
def repo() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def service(session: MagicMock, repo: MagicMock) -> InterviewPersistenceService:
    return InterviewPersistenceService(session, repo)


def _question(index: int) -> InterviewQuestion:
    return InterviewQuestion(
        question_index=index,
        question=f"Q{index}",
        type="JAVA",
        category="Java",
    )


def _make_orm(**overrides: object) -> InterviewSessionORM:
    defaults: dict[str, object] = {
        "id": 1,
        "session_id": "abc123",
        "skill_id": "java-backend",
        "difficulty": "mid",
        "resume_id": None,
        "total_questions": 3,
        "current_question_index": 0,
        "status": "CREATED",
        "questions_json": "[]",
        "llm_provider": None,
        "created_at": None,
        "completed_at": None,
        "overall_score": None,
    }
    defaults.update(overrides)
    return InterviewSessionORM(**defaults)  # type: ignore[arg-type]


class TestSaveSession:
    async def test_creates_orm_and_flushes(self, service: InterviewPersistenceService, repo: MagicMock) -> None:
        repo.save_session = AsyncMock()
        questions = [_question(0), _question(1)]

        await service.save_session(
            session_id="sess123",
            resume_id=42,
            total_questions=2,
            questions=questions,
            llm_provider="1",
            skill_id="java-backend",
            difficulty="mid",
        )

        repo.save_session.assert_awaited_once()
        orm_arg = repo.save_session.call_args.args[1]
        assert orm_arg.session_id == "sess123"
        assert orm_arg.status == SessionStatus.CREATED.value
        assert orm_arg.questions_json is not None


class TestFindBySessionId:
    async def test_returns_orm_when_found(self, service: InterviewPersistenceService, repo: MagicMock) -> None:
        orm = _make_orm()
        repo.find_by_session_id = AsyncMock(return_value=orm)

        result = await service.find_by_session_id("abc123")
        assert result is orm

    async def test_raises_when_not_found(self, service: InterviewPersistenceService, repo: MagicMock) -> None:
        repo.find_by_session_id = AsyncMock(return_value=None)

        with pytest.raises(BusinessException) as exc_info:
            await service.find_by_session_id("missing")
        assert exc_info.value.error_code == ErrorCode.INTERVIEW_SESSION_NOT_FOUND


class TestSaveAnswer:
    async def test_creates_new_answer(self, service: InterviewPersistenceService, repo: MagicMock) -> None:
        orm = _make_orm(id=10)
        repo.find_by_session_id = AsyncMock(return_value=orm)
        repo.find_answer_by_session_and_index = AsyncMock(return_value=None)
        repo.save_answer = AsyncMock()

        await service.save_answer("abc123", 0, "Q0", "JAVA", "answer0")

        repo.save_answer.assert_awaited_once()
        answer_arg = repo.save_answer.call_args.args[1]
        assert answer_arg.session_id == 10
        assert answer_arg.question_index == 0
        assert answer_arg.user_answer == "answer0"

    async def test_updates_existing_answer(self, service: InterviewPersistenceService, repo: MagicMock) -> None:
        orm = _make_orm(id=10)
        existing = InterviewAnswerORM(session_id=10, question_index=0, question="Q0", category="JAVA")
        repo.find_by_session_id = AsyncMock(return_value=orm)
        repo.find_answer_by_session_and_index = AsyncMock(return_value=existing)
        repo.save_answer = AsyncMock()

        await service.save_answer("abc123", 0, "Q0", "JAVA", "updated answer")

        repo.save_answer.assert_not_awaited()
        assert existing.user_answer == "updated answer"


class TestSerializeDeserialize:
    def test_roundtrip(self) -> None:
        questions = [
            _question(0),
            InterviewQuestion(
                question_index=1,
                question="Q1",
                type="MYSQL",
                category="MySQL",
                topic_summary="topic1",
                is_follow_up=True,
                parent_question_index=0,
            ),
        ]
        json_str = serialize_questions(questions)
        restored = deserialize_questions(json_str)

        assert len(restored) == 2
        assert restored[0].question == "Q0"
        assert restored[1].is_follow_up is True
        assert restored[1].parent_question_index == 0

    def test_serialize_includes_all_fields(self) -> None:
        q = InterviewQuestion(
            question_index=0,
            question="Q",
            type="JAVA",
            category="Java",
            topic_summary="topic",
            user_answer="A",
            score=80,
            feedback="good",
        )
        json_str = serialize_questions([q])
        assert "topicSummary" in json_str
        assert "userAnswer" in json_str
        assert "score" in json_str
        assert "feedback" in json_str
