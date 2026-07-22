from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.models.resume import Resume, ResumeAnalysis
from app.infrastructure.db.repositories.resume_repository import ResumeRepository


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    mock.delete = AsyncMock()
    return mock


@pytest.fixture()
def repo() -> ResumeRepository:
    return ResumeRepository()


def _make_resume(**overrides: object) -> Resume:
    defaults: dict[str, object] = {
        "id": 1,
        "file_hash": "abc123",
        "original_filename": "resume.pdf",
        "file_size": 1024,
        "content_type": "application/pdf",
        "storage_key": "resumes/2026/07/15/uuid_resume.pdf",
        "storage_url": "http://localhost:9000/interview-guide/resumes/2026/07/15/uuid_resume.pdf",
        "resume_text": "张三 Java 工程师",
        "uploaded_at": datetime(2026, 7, 15, 10, 0, 0),
        "last_accessed_at": datetime(2026, 7, 15, 10, 0, 0),
        "access_count": 1,
        "analyze_status": "PENDING",
        "analyze_error": None,
    }
    defaults.update(overrides)
    return Resume(**defaults)


class TestFindByHash:
    async def test_returns_resume_when_found(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resume = _make_resume()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = resume
        session.execute.return_value = mock_result

        result = await repo.find_by_hash(session, "abc123")

        assert result is resume

    async def test_returns_none_when_not_found(self, repo: ResumeRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        assert await repo.find_by_hash(session, "missing") is None


class TestGetById:
    async def test_returns_resume_when_found(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resume = _make_resume(id=42)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = resume
        session.execute.return_value = mock_result

        result = await repo.get_by_id(session, 42)

        assert result is resume
        assert result.id == 42

    async def test_returns_none_when_not_found(self, repo: ResumeRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        assert await repo.get_by_id(session, 999) is None


class TestSave:
    async def test_adds_and_flushes_returning_same_object(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resume = _make_resume(id=0)
        resume.id = None

        result = await repo.save(session, resume)

        session.add.assert_called_once_with(resume)
        session.flush.assert_called_once()
        assert result is resume


class TestListAll:
    async def test_returns_all_resumes(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resumes = [_make_resume(id=1), _make_resume(id=2)]
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = resumes
        session.execute.return_value = result_mock

        result = await repo.list_all(session)

        assert result == resumes


class TestCountAll:
    async def test_returns_count(self, repo: ResumeRepository, session: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.scalar.return_value = 3
        session.execute.return_value = result_mock

        assert await repo.count_all(session) == 3


class TestSumAccessCount:
    async def test_returns_sum(self, repo: ResumeRepository, session: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.scalar.return_value = 17
        session.execute.return_value = result_mock

        assert await repo.sum_access_count(session) == 17

    async def test_returns_zero_when_null(self, repo: ResumeRepository, session: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.scalar.return_value = None
        session.execute.return_value = result_mock

        assert await repo.sum_access_count(session) == 0


class TestDelete:
    async def test_deletes_resume(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resume = _make_resume()

        await repo.delete(session, resume)

        session.delete.assert_called_once_with(resume)


class TestIncrementAccessCount:
    async def test_increments_count_and_updates_timestamp(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resume = _make_resume(access_count=1)
        before = datetime.now(UTC)

        await repo.increment_access_count(session, resume)

        assert resume.access_count == 2
        assert resume.last_accessed_at is not None
        assert resume.last_accessed_at >= before
        session.flush.assert_called_once()


class TestFindLatestAnalysis:
    async def test_returns_latest_analysis(self, repo: ResumeRepository, session: AsyncMock) -> None:
        analysis = ResumeAnalysis(id=1, resume_id=1, overall_score=85)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = analysis
        session.execute.return_value = mock_result

        result = await repo.find_latest_analysis(session, 1)

        assert result is analysis

    async def test_returns_none_when_no_analysis(self, repo: ResumeRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        session.execute.return_value = mock_result

        assert await repo.find_latest_analysis(session, 1) is None


class TestFindAnalysesByResumeId:
    async def test_returns_analysis_list_ordered_desc(self, repo: ResumeRepository, session: AsyncMock) -> None:
        analyses = [ResumeAnalysis(id=2, resume_id=1), ResumeAnalysis(id=1, resume_id=1)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = analyses
        session.execute.return_value = mock_result

        result = await repo.find_analyses_by_resume_id(session, 1)

        assert result == analyses


class TestDeleteAnalysesByResumeId:
    async def test_deletes_and_returns_count(self, repo: ResumeRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.rowcount = 3
        session.execute.return_value = mock_result

        count = await repo.delete_analyses_by_resume_id(session, 1)

        assert count == 3


class TestUpdateAnalyzeStatus:
    async def test_sets_status_and_error(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resume = _make_resume(analyze_status="PENDING")

        await repo.update_analyze_status(session, resume, "PROCESSING", None)

        assert resume.analyze_status == "PROCESSING"
        assert resume.analyze_error is None
        session.flush.assert_called_once()

    async def test_sets_failed_status_with_error(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resume = _make_resume(analyze_status="PROCESSING")

        await repo.update_analyze_status(session, resume, "FAILED", "LLM 超时")

        assert resume.analyze_status == "FAILED"
        assert resume.analyze_error == "LLM 超时"

    async def test_clears_error_when_status_not_failed(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resume = _make_resume(analyze_status="FAILED", analyze_error="旧错误")

        await repo.update_analyze_status(session, resume, "COMPLETED", None)

        assert resume.analyze_status == "COMPLETED"
        assert resume.analyze_error is None


class TestSaveAnalysis:
    async def test_adds_and_flushes_returning_same_object(self, repo: ResumeRepository, session: AsyncMock) -> None:
        analysis = ResumeAnalysis(id=None, resume_id=1, overall_score=88)

        result = await repo.save_analysis(session, analysis)

        session.add.assert_called_once_with(analysis)
        session.flush.assert_called_once()
        assert result is analysis
