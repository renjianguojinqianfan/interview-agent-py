from collections.abc import Iterator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_resume_service
from app.api.rate_limit import limiter
from app.application.resume.schemas import (
    AnalysisHistoryDTO,
    ResumeDetailDTO,
    ResumeInfoDTO,
    ResumeListItemDTO,
    ResumePageDTO,
    ResumeUploadResponse,
    StorageInfoDTO,
)
from app.domain.errors import BusinessException, ErrorCode
from app.main import app

client = TestClient(app)


def _upload_response(resume_id: int = 1, duplicate: bool = False) -> ResumeUploadResponse:
    return ResumeUploadResponse(
        resume=ResumeInfoDTO(id=resume_id, filename="resume.pdf", analyze_status="PENDING"),
        storage=StorageInfoDTO(
            file_key="resumes/2026/07/15/uuid_resume.pdf",
            file_url="http://localhost:9000/bucket/resumes/2026/07/15/uuid_resume.pdf",
            resume_id=resume_id,
        ),
        duplicate=duplicate,
    )


def _page_dto() -> ResumePageDTO:
    return ResumePageDTO(
        items=[
            ResumeListItemDTO(
                id=1,
                filename="resume.pdf",
                file_size=1024,
                uploaded_at=datetime(2026, 7, 15, 10, 0, 0),
                access_count=1,
                latest_score=None,
                last_analyzed_at=None,
                analyze_status="PENDING",
                analyze_error=None,
            )
        ],
        total=1,
        page=1,
        size=10,
    )


def _detail_dto() -> ResumeDetailDTO:
    return ResumeDetailDTO(
        id=1,
        filename="resume.pdf",
        file_size=1024,
        content_type="application/pdf",
        storage_url="http://localhost:9000/bucket/key",
        uploaded_at=datetime(2026, 7, 15, 10, 0, 0),
        access_count=1,
        resume_text="张三 Java 工程师",
        analyze_status="PENDING",
        analyze_error=None,
        analyses=[],
    )


def _mock_service() -> MagicMock:
    service = MagicMock()
    service.upload = AsyncMock()
    service.list_resumes = AsyncMock()
    service.get_detail = AsyncMock()
    service.delete = AsyncMock()
    service.reanalyze = AsyncMock()
    service.export_pdf = AsyncMock()
    return service


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def mock_service() -> Iterator[MagicMock]:
    service = _mock_service()
    app.dependency_overrides[get_resume_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_resume_service, None)


class TestUploadResume:
    def test_returns_resume_id_and_pending_status(self, mock_service: MagicMock) -> None:
        mock_service.upload.return_value = _upload_response(resume_id=7)

        response = client.post(
            "/api/resumes/upload",
            files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["duplicate"] is False
        assert body["data"]["resume"]["id"] == 7
        assert body["data"]["resume"]["analyzeStatus"] == "PENDING"
        assert body["data"]["storage"]["resumeId"] == 7

    def test_duplicate_upload_returns_existing_resume(self, mock_service: MagicMock) -> None:
        mock_service.upload.return_value = _upload_response(resume_id=3, duplicate=True)

        response = client.post(
            "/api/resumes/upload",
            files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["duplicate"] is True
        assert body["data"]["resume"]["id"] == 3

    def test_unsupported_file_type_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.upload.side_effect = BusinessException(ErrorCode.RESUME_FILE_TYPE_NOT_SUPPORTED)

        response = client.post(
            "/api/resumes/upload",
            files={"file": ("photo.png", b"fake-png", "image/png")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == ErrorCode.RESUME_FILE_TYPE_NOT_SUPPORTED.code

    def test_rate_limit_blocks_sixth_request(self, mock_service: MagicMock) -> None:
        mock_service.upload.return_value = _upload_response(resume_id=1)

        results: list[int] = []
        for _ in range(6):
            response = client.post(
                "/api/resumes/upload",
                files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )
            results.append(response.json()["code"])

        assert results[:5] == [200, 200, 200, 200, 200]
        assert results[5] == ErrorCode.RATE_LIMIT_EXCEEDED.code


class TestListResumes:
    def test_returns_paginated_list(self, mock_service: MagicMock) -> None:
        mock_service.list_resumes.return_value = _page_dto()

        response = client.get("/api/resumes?page=1&size=10")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["total"] == 1
        assert body["data"]["page"] == 1
        assert body["data"]["size"] == 10
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["id"] == 1
        assert body["data"]["items"][0]["analyzeStatus"] == "PENDING"

    def test_uses_default_pagination(self, mock_service: MagicMock) -> None:
        mock_service.list_resumes.return_value = _page_dto()

        client.get("/api/resumes")

        mock_service.list_resumes.assert_awaited_once_with(page=1, size=10)


class TestGetResumeDetail:
    def test_returns_detail_with_analyses(self, mock_service: MagicMock) -> None:
        mock_service.get_detail.return_value = _detail_dto()

        response = client.get("/api/resumes/1/detail")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["id"] == 1
        assert body["data"]["resumeText"] == "张三 Java 工程师"
        assert body["data"]["analyses"] == []

    def test_not_found_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.get_detail.side_effect = BusinessException(ErrorCode.RESUME_NOT_FOUND)

        response = client.get("/api/resumes/999/detail")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == ErrorCode.RESUME_NOT_FOUND.code


class TestDeleteResume:
    def test_deletes_successfully(self, mock_service: MagicMock) -> None:
        mock_service.delete.return_value = None

        response = client.delete("/api/resumes/1")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"] is None

    def test_not_found_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.delete.side_effect = BusinessException(ErrorCode.RESUME_NOT_FOUND)

        response = client.delete("/api/resumes/999")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == ErrorCode.RESUME_NOT_FOUND.code


class TestResumeDetailWithAnalysis:
    def test_includes_analysis_history(self, mock_service: MagicMock) -> None:
        detail = _detail_dto()
        detail.analyses = [
            AnalysisHistoryDTO(
                id=1,
                overall_score=90,
                content_score=20,
                structure_score=18,
                skill_match_score=22,
                expression_score=14,
                project_score=16,
                summary="优秀简历",
                analyzed_at=datetime(2026, 7, 15, 11, 0, 0),
                strengths=["项目经验丰富"],
                suggestions=[{"category": "结构", "advice": "精简教育背景"}],
            )
        ]
        mock_service.get_detail.return_value = detail

        response = client.get("/api/resumes/1/detail")

        body = response.json()
        assert body["data"]["analyses"][0]["overallScore"] == 90
        assert body["data"]["analyses"][0]["strengths"] == ["项目经验丰富"]


class TestReanalyzeResume:
    def test_triggers_reanalyze_successfully(self, mock_service: MagicMock) -> None:
        mock_service.reanalyze.return_value = None

        response = client.post("/api/resumes/1/reanalyze")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        mock_service.reanalyze.assert_awaited_once_with(1)

    def test_not_found_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.reanalyze.side_effect = BusinessException(ErrorCode.RESUME_NOT_FOUND)

        response = client.post("/api/resumes/999/reanalyze")

        body = response.json()
        assert body["code"] == ErrorCode.RESUME_NOT_FOUND.code

    def test_rate_limit_blocks_third_request(self, mock_service: MagicMock) -> None:
        mock_service.reanalyze.return_value = None

        codes: list[int] = []
        for _ in range(3):
            response = client.post("/api/resumes/1/reanalyze")
            codes.append(response.json()["code"])

        assert codes[:2] == [200, 200]
        assert codes[2] == ErrorCode.RATE_LIMIT_EXCEEDED.code


class TestExportResumePdf:
    def test_returns_pdf_bytes(self, mock_service: MagicMock) -> None:
        mock_service.export_pdf.return_value = b"%PDF-1.4 fake report"

        response = client.get("/api/resumes/1/export")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == b"%PDF-1.4 fake report"
        assert "attachment" in response.headers["content-disposition"]

    def test_not_found_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.export_pdf.side_effect = BusinessException(ErrorCode.RESUME_NOT_FOUND)

        response = client.get("/api/resumes/999/export")

        body = response.json()
        assert body["code"] == ErrorCode.RESUME_NOT_FOUND.code

    def test_no_analysis_returns_error(self, mock_service: MagicMock) -> None:
        mock_service.export_pdf.side_effect = BusinessException(ErrorCode.RESUME_ANALYSIS_NOT_FOUND)

        response = client.get("/api/resumes/1/export")

        body = response.json()
        assert body["code"] == ErrorCode.RESUME_ANALYSIS_NOT_FOUND.code
