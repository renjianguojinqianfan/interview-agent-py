"""InterviewSessionService 单元测试：核心生命周期路径。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.interview.persistence_service import InterviewPersistenceService
from app.application.interview.question_service import QuestionService
from app.application.interview.schemas import (
    CreateSessionRequest,
    SubmitAnswerRequest,
)
from app.application.interview.session_service import InterviewSessionService
from app.domain.entities.interview import InterviewQuestion, SessionStatus
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM
from app.infrastructure.redis.session_cache import CachedSession


def _question(index: int) -> InterviewQuestion:
    return InterviewQuestion(
        question_index=index,
        question=f"Q{index}",
        type="JAVA",
        category="Java",
    )


def _questions_json(n: int) -> str:
    from app.application.interview.persistence_service import InterviewPersistenceService

    return InterviewPersistenceService.serialize_questions([_question(i) for i in range(n)])


def _make_orm(**overrides: object) -> InterviewSessionORM:
    defaults: dict[str, object] = {
        "id": 1,
        "session_id": "sess123",
        "skill_id": "java-backend",
        "difficulty": "mid",
        "resume_id": None,
        "total_questions": 3,
        "current_question_index": 0,
        "status": "CREATED",
        "questions_json": _questions_json(3),
        "llm_provider": None,
        "created_at": None,
        "completed_at": None,
        "overall_score": None,
    }
    defaults.update(overrides)
    return InterviewSessionORM(**defaults)  # type: ignore[arg-type]


@pytest.fixture()
def mock_session() -> MagicMock:
    mock = MagicMock()
    mock.commit = AsyncMock()
    return mock


@pytest.fixture()
def mock_question_service() -> MagicMock:
    service = MagicMock(spec=QuestionService)
    service.generate = AsyncMock()
    return service


@pytest.fixture()
def mock_persistence() -> MagicMock:
    service = MagicMock(spec=InterviewPersistenceService)
    service.save_session = AsyncMock()
    service.find_by_session_id = AsyncMock()
    service.find_by_session_id_optional = AsyncMock()
    service.update_session_status = AsyncMock()
    service.update_current_question_index = AsyncMock()
    service.update_evaluate_status = AsyncMock()
    service.save_answer = AsyncMock()
    service.find_unfinished_by_resume_id = AsyncMock()
    service.find_all_paginated = AsyncMock()
    service.find_answers_by_session_id = AsyncMock()
    service.get_historical_questions = AsyncMock(return_value=[])
    service.delete_session = AsyncMock()
    return service


@pytest.fixture()
def mock_cache() -> MagicMock:
    cache = MagicMock()
    cache.save_session = AsyncMock()
    cache.get_session = AsyncMock(return_value=None)
    cache.update_questions = AsyncMock()
    cache.update_current_index = AsyncMock()
    cache.update_status = AsyncMock()
    cache.refresh_ttl = AsyncMock()
    cache.find_unfinished_session_id = AsyncMock(return_value=None)
    cache.delete_session = AsyncMock()
    cache.delete_unfinished_mapping = AsyncMock()
    return cache


@pytest.fixture()
def mock_producer() -> MagicMock:
    producer = MagicMock()
    producer.send_task = AsyncMock()
    return producer


@pytest.fixture()
def mock_resume_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_by_id = AsyncMock()
    return repo


@pytest.fixture()
def service(
    mock_session: MagicMock,
    mock_question_service: MagicMock,
    mock_persistence: MagicMock,
    mock_cache: MagicMock,
    mock_producer: MagicMock,
    mock_resume_repo: MagicMock,
) -> InterviewSessionService:
    return InterviewSessionService(
        session=mock_session,
        question_service=mock_question_service,
        persistence_service=mock_persistence,
        session_cache=mock_cache,
        evaluate_producer=mock_producer,
        resume_repository=mock_resume_repo,
    )


class TestCreateSession:
    async def test_creates_session_without_resume(
        self,
        service: InterviewSessionService,
        mock_question_service: MagicMock,
        mock_persistence: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        mock_question_service.generate = AsyncMock(return_value=[_question(i) for i in range(3)])

        request = CreateSessionRequest(question_count=3, skill_id="java-backend")
        result = await service.create_session(request)

        assert result.total_questions == 3
        assert result.status == SessionStatus.CREATED.value
        mock_persistence.save_session.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    async def test_returns_existing_unfinished_session(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
        mock_question_service: MagicMock,
    ) -> None:
        mock_cache.find_unfinished_session_id = AsyncMock(return_value="existing123")
        mock_cache.get_session = AsyncMock(
            return_value=CachedSession(
                session_id="existing123",
                resume_text="",
                resume_id=42,
                questions_json=_questions_json(3),
                current_index=1,
                status="IN_PROGRESS",
            )
        )

        request = CreateSessionRequest(question_count=3, skill_id="java-backend", resume_id=42)
        result = await service.create_session(request)

        assert result.session_id == "existing123"
        mock_question_service.generate.assert_not_awaited()


class TestGetSession:
    async def test_returns_from_cache(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
    ) -> None:
        mock_cache.get_session = AsyncMock(
            return_value=CachedSession(
                session_id="sess123",
                resume_text="text",
                resume_id=None,
                questions_json=_questions_json(2),
                current_index=0,
                status="CREATED",
            )
        )

        result = await service.get_session("sess123")
        assert result.session_id == "sess123"
        assert result.total_questions == 2

    async def test_restores_from_db_when_cache_miss(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
        mock_persistence: MagicMock,
    ) -> None:
        mock_cache.get_session = AsyncMock(return_value=None)
        orm = _make_orm()
        mock_persistence.find_by_session_id_optional = AsyncMock(return_value=orm)
        mock_persistence.find_answers_by_session_id = AsyncMock(return_value=[])

        result = await service.get_session("sess123")
        assert result.session_id == "sess123"

    async def test_raises_when_not_found(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
        mock_persistence: MagicMock,
    ) -> None:
        mock_cache.get_session = AsyncMock(return_value=None)
        mock_persistence.find_by_session_id_optional = AsyncMock(return_value=None)

        with pytest.raises(BusinessException) as exc_info:
            await service.get_session("missing")
        assert exc_info.value.error_code == ErrorCode.INTERVIEW_SESSION_NOT_FOUND


class TestGetCurrentQuestion:
    async def test_returns_current_question(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
    ) -> None:
        mock_cache.get_session = AsyncMock(
            return_value=CachedSession(
                session_id="sess123",
                resume_text="",
                resume_id=None,
                questions_json=_questions_json(3),
                current_index=1,
                status="IN_PROGRESS",
            )
        )

        result = await service.get_current_question("sess123")
        assert result.completed is False
        assert result.question is not None
        assert result.question.question_index == 1

    async def test_transitions_created_to_in_progress(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
        mock_persistence: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        mock_cache.get_session = AsyncMock(
            return_value=CachedSession(
                session_id="sess123",
                resume_text="",
                resume_id=None,
                questions_json=_questions_json(3),
                current_index=0,
                status="CREATED",
            )
        )

        result = await service.get_current_question("sess123")
        assert result.completed is False
        mock_persistence.update_session_status.assert_awaited_once_with("sess123", SessionStatus.IN_PROGRESS.value)
        mock_session.commit.assert_awaited_once()

    async def test_returns_completed_when_all_answered(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
    ) -> None:
        mock_cache.get_session = AsyncMock(
            return_value=CachedSession(
                session_id="sess123",
                resume_text="",
                resume_id=None,
                questions_json=_questions_json(3),
                current_index=3,
                status="COMPLETED",
            )
        )

        result = await service.get_current_question("sess123")
        assert result.completed is True


class TestSubmitAnswer:
    async def test_submit_middle_question(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
        mock_persistence: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        mock_cache.get_session = AsyncMock(
            return_value=CachedSession(
                session_id="sess123",
                resume_text="",
                resume_id=None,
                questions_json=_questions_json(3),
                current_index=0,
                status="IN_PROGRESS",
            )
        )

        request = SubmitAnswerRequest(question_index=0, answer="answer0")
        result = await service.submit_answer("sess123", request)

        assert result.has_next_question is True
        assert result.current_index == 1
        assert result.total_questions == 3
        mock_persistence.update_current_question_index.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    async def test_submit_last_question_completes_and_enqueues(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
        mock_persistence: MagicMock,
        mock_producer: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        mock_cache.get_session = AsyncMock(
            return_value=CachedSession(
                session_id="sess123",
                resume_text="",
                resume_id=None,
                questions_json=_questions_json(2),
                current_index=1,
                status="IN_PROGRESS",
            )
        )

        request = SubmitAnswerRequest(question_index=1, answer="answer1")
        result = await service.submit_answer("sess123", request)

        assert result.has_next_question is False
        mock_persistence.update_session_status.assert_awaited_once_with("sess123", SessionStatus.COMPLETED.value)
        mock_persistence.update_evaluate_status.assert_awaited_once_with("sess123", "PENDING", None)
        mock_producer.send_task.assert_awaited_once()
        payload = mock_producer.send_task.call_args.args[0]
        assert payload.session_id == "sess123"


class TestCompleteInterview:
    async def test_completes_and_enqueues(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
        mock_persistence: MagicMock,
        mock_producer: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        mock_cache.get_session = AsyncMock(
            return_value=CachedSession(
                session_id="sess123",
                resume_text="",
                resume_id=None,
                questions_json=_questions_json(3),
                current_index=1,
                status="IN_PROGRESS",
            )
        )

        await service.complete_interview("sess123")

        mock_persistence.update_session_status.assert_awaited_once_with("sess123", SessionStatus.COMPLETED.value)
        mock_producer.send_task.assert_awaited_once()

    async def test_raises_when_already_completed(
        self,
        service: InterviewSessionService,
        mock_cache: MagicMock,
    ) -> None:
        mock_cache.get_session = AsyncMock(
            return_value=CachedSession(
                session_id="sess123",
                resume_text="",
                resume_id=None,
                questions_json=_questions_json(3),
                current_index=3,
                status="COMPLETED",
            )
        )

        with pytest.raises(BusinessException) as exc_info:
            await service.complete_interview("sess123")
        assert exc_info.value.error_code == ErrorCode.INTERVIEW_ALREADY_COMPLETED


class TestDeleteSession:
    async def test_deletes_session_and_cache(
        self,
        service: InterviewSessionService,
        mock_persistence: MagicMock,
        mock_cache: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        orm = _make_orm(resume_id=None)
        mock_persistence.find_by_session_id_optional = AsyncMock(return_value=orm)

        await service.delete_session("sess123")

        mock_persistence.delete_session.assert_awaited_once_with("sess123")
        mock_session.commit.assert_awaited_once()
        mock_cache.delete_session.assert_awaited_once_with("sess123")

    async def test_noop_when_not_found(
        self,
        service: InterviewSessionService,
        mock_persistence: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        mock_persistence.find_by_session_id_optional = AsyncMock(return_value=None)

        await service.delete_session("missing")

        mock_persistence.delete_session.assert_not_awaited()
        mock_session.commit.assert_not_awaited()
