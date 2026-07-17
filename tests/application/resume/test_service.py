import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.resume.schemas import (
    ResumeDetailDTO,
    ResumePageDTO,
    ResumeUploadResponse,
)
from app.application.resume.service import ResumeService
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.resume import Resume, ResumeAnalysis


def _make_resume(**overrides: object) -> Resume:
    defaults: dict[str, object] = {
        "id": 1,
        "file_hash": "abc123",
        "original_filename": "resume.pdf",
        "file_size": 1024,
        "content_type": "application/pdf",
        "storage_key": "resumes/2026/07/15/uuid_resume.pdf",
        "storage_url": "http://localhost:9000/bucket/resumes/2026/07/15/uuid_resume.pdf",
        "resume_text": "张三 Java 工程师",
        "uploaded_at": datetime(2026, 7, 15, 10, 0, 0),
        "last_accessed_at": datetime(2026, 7, 15, 10, 0, 0),
        "access_count": 1,
        "analyze_status": "PENDING",
        "analyze_error": None,
    }
    defaults.update(overrides)
    return Resume(**defaults)


def _make_service() -> tuple[ResumeService, dict[str, MagicMock | AsyncMock]]:
    session = MagicMock()
    session.commit = AsyncMock()
    repository = MagicMock()
    repository.find_by_hash = AsyncMock()
    repository.get_by_id = AsyncMock()
    repository.save = AsyncMock(side_effect=lambda _session, resume: setattr(resume, "id", 1) or resume)
    repository.list_paginated = AsyncMock()
    repository.delete = AsyncMock()
    repository.increment_access_count = AsyncMock()
    repository.find_latest_analysis = AsyncMock()
    repository.find_analyses_by_resume_id = AsyncMock()
    repository.delete_analyses_by_resume_id = AsyncMock()

    repository.update_analyze_status = AsyncMock()
    repository.save_analysis = AsyncMock()

    parser = MagicMock()
    hash_service = MagicMock()
    content_detector = MagicMock()
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.build_file_url = MagicMock()
    storage.delete_file = AsyncMock()

    producer = MagicMock()
    producer.send_task = AsyncMock(return_value="100-0")

    pdf_service = MagicMock()
    pdf_service.export_resume_analysis = AsyncMock(return_value=b"%PDF-1.4 fake")

    service = ResumeService(
        session=session,
        repository=repository,
        parser=parser,
        hash_service=hash_service,
        content_detector=content_detector,
        storage=storage,
        producer=producer,
        pdf_service=pdf_service,
        allowed_types=[
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/plain",
            "text/markdown",
        ],
        max_file_size=10 * 1024 * 1024,
    )
    return service, {
        "session": session,
        "repository": repository,
        "parser": parser,
        "hash_service": hash_service,
        "content_detector": content_detector,
        "storage": storage,
        "producer": producer,
        "pdf_service": pdf_service,
    }


PDF_BYTES = b"%PDF-1.4 fake pdf content"


class TestUploadNewResume:
    async def test_returns_resume_id_and_pending_status(self) -> None:
        service, deps = _make_service()
        deps["content_detector"].detect.return_value = "application/pdf"
        deps["hash_service"].calculate_hash.return_value = "abc123"
        deps["repository"].find_by_hash.return_value = None
        deps["parser"].parse_content.return_value = "张三 Java 工程师"
        deps["storage"].upload_file.return_value = "resumes/2026/07/15/uuid_resume.pdf"
        deps["storage"].build_file_url.return_value = "http://localhost:9000/bucket/key"

        deps["repository"].save.side_effect = lambda _session, resume: setattr(resume, "id", 7) or resume

        result = await service.upload("resume.pdf", "application/pdf", PDF_BYTES)

        assert isinstance(result, ResumeUploadResponse)
        assert result.duplicate is False
        assert result.resume.id == 7
        assert result.resume.filename == "resume.pdf"
        assert result.resume.analyze_status == "PENDING"
        assert result.storage.file_key == "resumes/2026/07/15/uuid_resume.pdf"
        assert result.storage.file_url == "http://localhost:9000/bucket/key"
        assert result.storage.resume_id == 7

    async def test_saves_resume_with_pending_analyze_status(self) -> None:
        service, deps = _make_service()
        deps["content_detector"].detect.return_value = "application/pdf"
        deps["hash_service"].calculate_hash.return_value = "abc123"
        deps["repository"].find_by_hash.return_value = None
        deps["parser"].parse_content.return_value = "resume text"
        deps["storage"].upload_file.return_value = "key"
        deps["storage"].build_file_url.return_value = "url"

        captured: list[Resume] = []

        def save_side_effect(_session: object, resume: Resume) -> Resume:
            resume.id = 5
            captured.append(resume)
            return resume

        deps["repository"].save.side_effect = save_side_effect

        await service.upload("resume.pdf", "application/pdf", PDF_BYTES)

        assert len(captured) == 1
        saved = captured[0]
        assert saved.file_hash == "abc123"
        assert saved.original_filename == "resume.pdf"
        assert saved.analyze_status == "PENDING"
        assert saved.resume_text == "resume text"
        assert saved.storage_key == "key"
        assert saved.storage_url == "url"

    async def test_commits_after_save(self) -> None:
        service, deps = _make_service()
        deps["content_detector"].detect.return_value = "application/pdf"
        deps["hash_service"].calculate_hash.return_value = "abc123"
        deps["repository"].find_by_hash.return_value = None
        deps["parser"].parse_content.return_value = "text"
        deps["storage"].upload_file.return_value = "key"
        deps["storage"].build_file_url.return_value = "url"

        await service.upload("resume.pdf", "application/pdf", PDF_BYTES)

        deps["session"].commit.assert_awaited_once()


class TestUploadDuplicate:
    async def test_returns_existing_resume_with_duplicate_true(self) -> None:
        service, deps = _make_service()
        existing = _make_resume(id=3, file_hash="abc123", original_filename="old.pdf")
        deps["content_detector"].detect.return_value = "application/pdf"
        deps["hash_service"].calculate_hash.return_value = "abc123"
        deps["repository"].find_by_hash.return_value = existing

        result = await service.upload("resume.pdf", "application/pdf", PDF_BYTES)

        assert result.duplicate is True
        assert result.resume.id == 3
        assert result.storage.resume_id == 3

    async def test_increments_access_count_on_duplicate(self) -> None:
        service, deps = _make_service()
        existing = _make_resume(id=3, access_count=1)
        deps["content_detector"].detect.return_value = "application/pdf"
        deps["hash_service"].calculate_hash.return_value = "abc123"
        deps["repository"].find_by_hash.return_value = existing

        await service.upload("resume.pdf", "application/pdf", PDF_BYTES)

        deps["repository"].increment_access_count.assert_awaited_once()
        deps["session"].commit.assert_awaited_once()

    async def test_does_not_parse_or_store_on_duplicate(self) -> None:
        service, deps = _make_service()
        existing = _make_resume(id=3)
        deps["content_detector"].detect.return_value = "application/pdf"
        deps["hash_service"].calculate_hash.return_value = "abc123"
        deps["repository"].find_by_hash.return_value = existing

        await service.upload("resume.pdf", "application/pdf", PDF_BYTES)

        deps["parser"].parse_content.assert_not_called()
        deps["storage"].upload_file.assert_not_awaited()
        deps["repository"].save.assert_not_called()


class TestUploadValidation:
    async def test_rejects_unsupported_file_type(self) -> None:
        service, deps = _make_service()
        deps["content_detector"].detect.return_value = "image/png"

        with pytest.raises(BusinessException) as exc_info:
            await service.upload("photo.png", "image/png", b"fake-png")

        assert exc_info.value.error_code == ErrorCode.RESUME_FILE_TYPE_NOT_SUPPORTED

    async def test_rejects_oversized_file(self) -> None:
        service, _ = _make_service()

        with pytest.raises(BusinessException) as exc_info:
            await service.upload("big.pdf", "application/pdf", b"x" * (10 * 1024 * 1024 + 1))

        assert exc_info.value.error_code == ErrorCode.RESUME_UPLOAD_FAILED

    async def test_rejects_empty_parsed_text(self) -> None:
        service, deps = _make_service()
        deps["content_detector"].detect.return_value = "application/pdf"
        deps["hash_service"].calculate_hash.return_value = "abc123"
        deps["repository"].find_by_hash.return_value = None
        deps["parser"].parse_content.return_value = "   "

        with pytest.raises(BusinessException) as exc_info:
            await service.upload("resume.pdf", "application/pdf", PDF_BYTES)

        assert exc_info.value.error_code == ErrorCode.RESUME_PARSE_FAILED


class TestListResumes:
    async def test_returns_paginated_items_and_total(self) -> None:
        service, deps = _make_service()
        resumes = [_make_resume(id=1), _make_resume(id=2)]
        deps["repository"].list_paginated.return_value = (resumes, 2)
        deps["repository"].find_latest_analysis.return_value = None

        result = await service.list_resumes(page=1, size=10)

        assert isinstance(result, ResumePageDTO)
        assert result.total == 2
        assert result.page == 1
        assert result.size == 10
        assert len(result.items) == 2
        assert result.items[0].id == 1
        assert result.items[0].latest_score is None
        assert result.items[0].interview_count == 0
        assert result.items[0].analyze_status == "PENDING"

    async def test_populates_latest_score_when_analysis_exists(self) -> None:
        service, deps = _make_service()
        resume = _make_resume(id=1, analyze_status="COMPLETED")
        deps["repository"].list_paginated.return_value = ([resume], 1)
        analysis = ResumeAnalysis(id=1, resume_id=1, overall_score=88)
        deps["repository"].find_latest_analysis.return_value = analysis

        result = await service.list_resumes(page=1, size=10)

        assert result.items[0].latest_score == 88


class TestGetDetail:
    async def test_returns_detail_with_analyses(self) -> None:
        service, deps = _make_service()
        resume = _make_resume(id=1, analyze_status="COMPLETED")
        deps["repository"].get_by_id.return_value = resume
        analysis = ResumeAnalysis(
            id=1,
            resume_id=1,
            overall_score=90,
            content_score=20,
            structure_score=18,
            skill_match_score=22,
            expression_score=14,
            project_score=16,
            summary="优秀简历",
            strengths_json=json.dumps(["项目经验丰富", "技能匹配度高"]),
            suggestions_json=json.dumps([{"category": "结构", "advice": "精简教育背景"}]),
            analyzed_at=datetime(2026, 7, 15, 11, 0, 0),
        )
        deps["repository"].find_analyses_by_resume_id.return_value = [analysis]

        result = await service.get_detail(1)

        assert isinstance(result, ResumeDetailDTO)
        assert result.id == 1
        assert result.resume_text == "张三 Java 工程师"
        assert len(result.analyses) == 1
        assert result.analyses[0].overall_score == 90
        assert result.analyses[0].strengths == ["项目经验丰富", "技能匹配度高"]
        assert result.analyses[0].suggestions == [{"category": "结构", "advice": "精简教育背景"}]

    async def test_raises_not_found_when_missing(self) -> None:
        service, deps = _make_service()
        deps["repository"].get_by_id.return_value = None

        with pytest.raises(BusinessException) as exc_info:
            await service.get_detail(999)

        assert exc_info.value.error_code == ErrorCode.RESUME_NOT_FOUND


class TestDeleteResume:
    async def test_deletes_storage_file_and_db_records(self) -> None:
        service, deps = _make_service()
        resume = _make_resume(id=1, storage_key="resumes/key.pdf")
        deps["repository"].get_by_id.return_value = resume
        deps["repository"].delete_analyses_by_resume_id.return_value = 2

        await service.delete(1)

        deps["storage"].delete_file.assert_awaited_once_with("resumes/key.pdf")
        deps["repository"].delete_analyses_by_resume_id.assert_awaited_once()
        deps["repository"].delete.assert_awaited_once()
        deps["session"].commit.assert_awaited_once()

    async def test_raises_not_found_when_missing(self) -> None:
        service, deps = _make_service()
        deps["repository"].get_by_id.return_value = None

        with pytest.raises(BusinessException) as exc_info:
            await service.delete(999)

        assert exc_info.value.error_code == ErrorCode.RESUME_NOT_FOUND

    async def test_continues_db_delete_when_storage_delete_fails(self) -> None:
        service, deps = _make_service()
        resume = _make_resume(id=1, storage_key="resumes/key.pdf")
        deps["repository"].get_by_id.return_value = resume
        deps["storage"].delete_file.side_effect = Exception("S3 down")

        await service.delete(1)

        deps["repository"].delete.assert_awaited_once()
        deps["session"].commit.assert_awaited_once()


class TestUploadEnqueue:
    async def test_enqueues_analyze_task_after_commit(self) -> None:
        service, deps = _make_service()
        deps["content_detector"].detect.return_value = "application/pdf"
        deps["hash_service"].calculate_hash.return_value = "abc123"
        deps["repository"].find_by_hash.return_value = None
        deps["parser"].parse_content.return_value = "text"
        deps["storage"].upload_file.return_value = "key"
        deps["storage"].build_file_url.return_value = "url"

        await service.upload("resume.pdf", "application/pdf", PDF_BYTES)

        deps["session"].commit.assert_awaited_once()
        deps["producer"].send_task.assert_awaited_once()
        payload = deps["producer"].send_task.call_args.args[0]
        assert payload.resume_id == 1

    async def test_does_not_enqueue_on_duplicate(self) -> None:
        service, deps = _make_service()
        existing = _make_resume(id=3)
        deps["content_detector"].detect.return_value = "application/pdf"
        deps["hash_service"].calculate_hash.return_value = "abc123"
        deps["repository"].find_by_hash.return_value = existing

        await service.upload("resume.pdf", "application/pdf", PDF_BYTES)

        deps["producer"].send_task.assert_not_awaited()


class TestReanalyze:
    async def test_resets_to_pending_and_enqueues(self) -> None:
        service, deps = _make_service()
        resume = _make_resume(id=1, analyze_status="COMPLETED", analyze_error="old err")
        deps["repository"].get_by_id.return_value = resume

        await service.reanalyze(1)

        deps["repository"].update_analyze_status.assert_awaited_once()
        args = deps["repository"].update_analyze_status.call_args.args
        assert args[2] == "PENDING"
        assert args[3] is None
        deps["session"].commit.assert_awaited_once()
        deps["producer"].send_task.assert_awaited_once()

    async def test_raises_not_found_when_missing(self) -> None:
        service, deps = _make_service()
        deps["repository"].get_by_id.return_value = None

        with pytest.raises(BusinessException) as exc_info:
            await service.reanalyze(999)

        assert exc_info.value.error_code == ErrorCode.RESUME_NOT_FOUND


class TestExportPdf:
    async def test_returns_pdf_bytes(self) -> None:
        service, deps = _make_service()
        resume = _make_resume(id=1)
        analysis = ResumeAnalysis(id=1, resume_id=1, overall_score=85)
        deps["repository"].get_by_id.return_value = resume
        deps["repository"].find_latest_analysis.return_value = analysis

        result = await service.export_pdf(1)

        assert result == b"%PDF-1.4 fake"
        deps["pdf_service"].export_resume_analysis.assert_awaited_once()

    async def test_raises_not_found_when_resume_missing(self) -> None:
        service, deps = _make_service()
        deps["repository"].get_by_id.return_value = None

        with pytest.raises(BusinessException) as exc_info:
            await service.export_pdf(999)

        assert exc_info.value.error_code == ErrorCode.RESUME_NOT_FOUND

    async def test_raises_when_no_analysis(self) -> None:
        service, deps = _make_service()
        deps["repository"].get_by_id.return_value = _make_resume(id=1)
        deps["repository"].find_latest_analysis.return_value = None

        with pytest.raises(BusinessException) as exc_info:
            await service.export_pdf(1)

        assert exc_info.value.error_code == ErrorCode.RESUME_ANALYSIS_NOT_FOUND
