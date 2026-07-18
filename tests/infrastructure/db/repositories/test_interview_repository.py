from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.models.interview import InterviewAnswer as InterviewAnswerORM
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM
from app.infrastructure.db.repositories.interview_repository import InterviewRepository


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    mock.delete = AsyncMock()
    return mock


@pytest.fixture()
def repo() -> InterviewRepository:
    return InterviewRepository()


def _make_session_orm(**overrides: object) -> InterviewSessionORM:
    defaults: dict[str, object] = {
        "session_id": "abc1234567890def",
        "skill_id": "java-backend",
        "difficulty": "mid",
        "total_questions": 5,
        "current_question_index": 0,
        "status": "CREATED",
        "questions_json": "[]",
        "created_at": datetime(2026, 7, 18, 10, 0, 0),
    }
    defaults.update(overrides)
    return InterviewSessionORM(**defaults)  # type: ignore[arg-type]


def _make_answer_orm(**overrides: object) -> InterviewAnswerORM:
    defaults: dict[str, object] = {
        "session_id": 1,
        "question_index": 0,
        "question": "Q1",
        "category": "JAVA",
        "user_answer": "A1",
    }
    defaults.update(overrides)
    return InterviewAnswerORM(**defaults)  # type: ignore[arg-type]


class TestSaveSession:
    async def test_adds_and_flushes(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orm = _make_session_orm()
        result = await repo.save_session(session, orm)
        session.add.assert_called_once_with(orm)
        session.flush.assert_awaited_once()
        assert result is orm


class TestFindBySessionId:
    async def test_returns_session_when_found(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orm = _make_session_orm()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = orm
        session.execute.return_value = mock_result

        result = await repo.find_by_session_id(session, "abc1234567890def")
        assert result is orm

    async def test_returns_none_when_not_found(self, repo: InterviewRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        assert await repo.find_by_session_id(session, "missing") is None


class TestUpdateSessionStatus:
    async def test_updates_status(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orm = _make_session_orm(status="CREATED")
        await repo.update_session_status(session, orm, "IN_PROGRESS")
        assert orm.status == "IN_PROGRESS"
        session.flush.assert_awaited_once()

    async def test_sets_completed_at_on_completed(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orm = _make_session_orm(status="IN_PROGRESS", completed_at=None)
        await repo.update_session_status(session, orm, "COMPLETED")
        assert orm.status == "COMPLETED"
        assert orm.completed_at is not None

    async def test_sets_completed_at_on_evaluated(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orm = _make_session_orm(status="COMPLETED", completed_at=None)
        await repo.update_session_status(session, orm, "EVALUATED")
        assert orm.completed_at is not None


class TestUpdateCurrentQuestionIndex:
    async def test_updates_index_only(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orm = _make_session_orm(current_question_index=0, status="CREATED")
        await repo.update_current_question_index(session, orm, 2)
        assert orm.current_question_index == 2
        assert orm.status == "CREATED"


class TestUpdateEvaluateStatus:
    async def test_updates_status_and_error(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orm = _make_session_orm()
        await repo.update_evaluate_status(session, orm, "PENDING", None)
        assert orm.evaluate_status == "PENDING"
        assert orm.evaluate_error is None

    async def test_sets_error(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orm = _make_session_orm()
        await repo.update_evaluate_status(session, orm, "FAILED", "timeout")
        assert orm.evaluate_status == "FAILED"
        assert orm.evaluate_error == "timeout"


class TestFindUnfinishedByResumeId:
    async def test_returns_session_when_found(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orm = _make_session_orm()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = orm
        session.execute.return_value = mock_result

        result = await repo.find_unfinished_by_resume_id(session, 42)
        assert result is orm

    async def test_returns_none_when_not_found(self, repo: InterviewRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        session.execute.return_value = mock_result

        assert await repo.find_unfinished_by_resume_id(session, 999) is None


class TestFindAllPaginated:
    async def test_returns_items_and_total(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orms = [_make_session_orm(), _make_session_orm()]
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = orms
        count_result = MagicMock()
        count_result.scalar.return_value = 2
        session.execute.side_effect = [items_result, count_result]

        items, total = await repo.find_all_paginated(session, page=1, size=10)
        assert len(items) == 2
        assert total == 2


class TestSaveAnswer:
    async def test_adds_and_flushes(self, repo: InterviewRepository, session: AsyncMock) -> None:
        answer = _make_answer_orm()
        result = await repo.save_answer(session, answer)
        session.add.assert_called_once_with(answer)
        session.flush.assert_awaited_once()
        assert result is answer


class TestFindAnswerBySessionAndIndex:
    async def test_returns_answer_when_found(self, repo: InterviewRepository, session: AsyncMock) -> None:
        answer = _make_answer_orm()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = answer
        session.execute.return_value = mock_result

        result = await repo.find_answer_by_session_and_index(session, 1, 0)
        assert result is answer

    async def test_returns_none_when_not_found(self, repo: InterviewRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        assert await repo.find_answer_by_session_and_index(session, 1, 99) is None


class TestFindAnswersBySessionId:
    async def test_returns_ordered_answers(self, repo: InterviewRepository, session: AsyncMock) -> None:
        answers = [_make_answer_orm(question_index=0), _make_answer_orm(question_index=1)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = answers
        session.execute.return_value = mock_result

        result = await repo.find_answers_by_session_id(session, 1)
        assert len(result) == 2


class TestFindRecentSessionsForHistory:
    async def test_with_resume_id(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orms = [_make_session_orm()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = orms
        session.execute.return_value = mock_result

        result = await repo.find_recent_sessions_for_history(session, "java-backend", 42)
        assert len(result) == 1

    async def test_without_resume_id(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orms = [_make_session_orm()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = orms
        session.execute.return_value = mock_result

        result = await repo.find_recent_sessions_for_history(session, "java-backend", None)
        assert len(result) == 1


class TestDelete:
    async def test_deletes_session(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orm = _make_session_orm()
        await repo.delete(session, orm)
        session.delete.assert_awaited_once_with(orm)
