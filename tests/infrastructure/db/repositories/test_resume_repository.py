from datetime import datetime
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


class TestListPaginated:
    async def test_returns_items_and_total_for_first_page(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resumes = [_make_resume(id=1), _make_resume(id=2)]
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = resumes
        count_result = MagicMock()
        count_result.scalar.return_value = 2
        session.execute.side_effect = [items_result, count_result]

        items, total = await repo.list_paginated(session, page=1, size=10)

        assert items == resumes
        assert total == 2

    async def test_returns_empty_when_no_resumes(self, repo: ResumeRepository, session: AsyncMock) -> None:
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = []
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        session.execute.side_effect = [items_result, count_result]

        items, total = await repo.list_paginated(session, page=1, size=10)

        assert items == []
        assert total == 0


class TestDelete:
    async def test_deletes_resume(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resume = _make_resume()

        await repo.delete(session, resume)

        session.delete.assert_called_once_with(resume)


class TestIncrementAccessCount:
    async def test_increments_count_and_updates_timestamp(self, repo: ResumeRepository, session: AsyncMock) -> None:
        resume = _make_resume(access_count=1)
        before = datetime.now()

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
