from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.entities.evaluation import EvaluationReport, ReferenceAnswer
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


class TestFindAll:
    async def test_returns_all_sessions(self, repo: InterviewRepository, session: AsyncMock) -> None:
        orms = [_make_session_orm(), _make_session_orm()]
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = orms
        session.execute.return_value = result_mock

        result = await repo.find_all(session)

        assert result == orms


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


def _make_report(
    overall_score: int = 85,
    overall_feedback: str = "优秀",
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
    reference_answers: list[ReferenceAnswer] | None = None,
) -> EvaluationReport:
    return EvaluationReport(
        session_id="sess123",
        total_questions=2,
        overall_score=overall_score,
        category_scores=[],
        question_details=[],
        overall_feedback=overall_feedback,
        strengths=strengths or ["扎实"],
        improvements=improvements or ["需补深度"],
        reference_answers=reference_answers
        or [ReferenceAnswer(question_index=0, question="Q", reference_answer="A", key_points=[])],
    )


class TestSaveEvaluationResult:
    async def test_writes_evaluation_fields_and_evaluated_status(
        self, repo: InterviewRepository, session: AsyncMock
    ) -> None:
        orm = _make_session_orm(status="COMPLETED")
        await repo.save_evaluation_result(session, orm, _make_report())
        assert orm.overall_score == 85
        assert orm.overall_feedback == "优秀"
        assert "扎实" in orm.strengths_json
        assert "需补深度" in orm.improvements_json
        assert "questionIndex" in orm.reference_answers_json
        assert orm.status == "EVALUATED"
        session.flush.assert_awaited_once()

    async def test_preserves_completed_at_from_completed_phase(
        self, repo: InterviewRepository, session: AsyncMock
    ) -> None:
        """P1: EVALUATED 不覆写 completed_at，保留 COMPLETED 阶段设置的面试结束时间。"""
        original_completed_at = datetime(2026, 7, 18, 10, 0, 0)
        orm = _make_session_orm(status="COMPLETED")
        orm.completed_at = original_completed_at
        await repo.save_evaluation_result(session, orm, _make_report())
        assert orm.completed_at == original_completed_at


class TestUpdateAnswerEvaluation:
    async def test_writes_score_feedback_reference_keypoints(
        self, repo: InterviewRepository, session: AsyncMock
    ) -> None:
        answer = _make_answer_orm(question_index=0)
        await repo.update_answer_evaluation(
            session,
            answer,
            score=90,
            feedback="回答优秀",
            reference_answer="标准答案",
            key_points_json='["要点1"]',
        )
        assert answer.score == 90
        assert answer.feedback == "回答优秀"
        assert answer.reference_answer == "标准答案"
        assert answer.key_points_json == '["要点1"]'
        session.flush.assert_awaited_once()


class TestCountAll:
    async def test_returns_count(self, repo: InterviewRepository, session: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.scalar.return_value = 4
        session.execute.return_value = result_mock

        assert await repo.count_all(session) == 4


class TestCountByResumeIds:
    async def test_returns_empty_for_empty_ids(self, repo: InterviewRepository, session: AsyncMock) -> None:
        assert await repo.count_by_resume_ids(session, []) == {}
        session.execute.assert_not_awaited()

    async def test_maps_resume_id_to_count(self, repo: InterviewRepository, session: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.all.return_value = [(1, 3), (2, 1)]
        session.execute.return_value = result_mock

        result = await repo.count_by_resume_ids(session, [1, 2])

        assert result == {1: 3, 2: 1}

    async def test_skips_null_resume_id(self, repo: InterviewRepository, session: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.all.return_value = [(None, 2), (1, 3)]
        session.execute.return_value = result_mock

        result = await repo.count_by_resume_ids(session, [1])

        assert result == {1: 3}


class TestFindByResumeId:
    async def test_returns_sessions_for_resume(self, repo: InterviewRepository, session: AsyncMock) -> None:
        sessions = [_make_session_orm(session_id="s1"), _make_session_orm(session_id="s2")]
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = sessions
        session.execute.return_value = result_mock

        result = await repo.find_by_resume_id(session, 1)

        assert result == sessions
