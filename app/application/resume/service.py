import asyncio
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.resume.schemas import (
    AnalysisHistoryDTO,
    ResumeDetailDTO,
    ResumeInfoDTO,
    ResumeListItemDTO,
    ResumePageDTO,
    ResumeUploadResponse,
    StorageInfoDTO,
)
from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.resume import Resume, ResumeAnalysis
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.export.pdf import PdfExportService
from app.infrastructure.parsing.content_type import ContentTypeDetector
from app.infrastructure.parsing.parser import DocumentParser
from app.infrastructure.storage.hash import FileHashService
from app.infrastructure.storage.s3 import S3StorageService
from app.infrastructure.tasks.resume_analyze_producer import AnalyzeStreamProducer, ResumeAnalyzePayload

logger = logging.getLogger(__name__)

_RESUME_STORAGE_PREFIX = "resumes"


class ResumeService:
    """简历业务编排：上传(检测->去重->解析->存储->入库)、列表、详情、删除。"""

    def __init__(
        self,
        session: AsyncSession,
        repository: ResumeRepository,
        parser: DocumentParser,
        hash_service: FileHashService,
        content_detector: ContentTypeDetector,
        storage: S3StorageService,
        producer: AnalyzeStreamProducer,
        pdf_service: PdfExportService,
        allowed_types: list[str],
        max_file_size: int,
    ) -> None:
        self._session = session
        self._repository = repository
        self._parser = parser
        self._hash_service = hash_service
        self._content_detector = content_detector
        self._storage = storage
        self._producer = producer
        self._pdf_service = pdf_service
        self._allowed_types = allowed_types
        self._max_file_size = max_file_size

    async def upload(self, filename: str, content_type: str, data: bytes) -> ResumeUploadResponse:
        self._validate_size(data)
        detected_type = self._content_detector.detect(data, filename)
        if not self._is_allowed(detected_type):
            raise BusinessException(
                ErrorCode.RESUME_FILE_TYPE_NOT_SUPPORTED,
                f"不支持的文件类型: {detected_type}",
            )

        file_hash = self._hash_service.calculate_hash(data)
        existing = await self._repository.find_by_hash(self._session, file_hash)
        if existing is not None:
            logger.info("检测到重复简历: hash=%s, resumeId=%s", file_hash, existing.id)
            await self._repository.increment_access_count(self._session, existing)
            await self._session.commit()
            return self._build_duplicate_response(existing)

        resume_text = await asyncio.to_thread(self._parser.parse_content, data, filename)
        if not resume_text.strip():
            raise BusinessException(
                ErrorCode.RESUME_PARSE_FAILED,
                "无法从文件中提取文本内容，请确保文件不是扫描版PDF",
            )

        storage_key = await self._storage.upload_file(data, filename, _RESUME_STORAGE_PREFIX)
        storage_url = self._storage.build_file_url(storage_key)

        resume = Resume(
            file_hash=file_hash,
            original_filename=filename,
            file_size=len(data),
            content_type=content_type or detected_type,
            storage_key=storage_key,
            storage_url=storage_url,
            resume_text=resume_text,
            access_count=1,
            analyze_status=AsyncTaskStatus.PENDING.value,
        )
        await self._repository.save(self._session, resume)
        await self._session.commit()
        logger.info("简历上传完成: resumeId=%s, filename=%s", resume.id, filename)
        await self._enqueue_analyze(resume.id)

        return ResumeUploadResponse(
            resume=self._to_resume_info(resume),
            storage=StorageInfoDTO(
                file_key=storage_key,
                file_url=storage_url,
                resume_id=resume.id,
            ),
            duplicate=False,
        )

    async def list_resumes(self, page: int, size: int) -> ResumePageDTO:
        resumes, total = await self._repository.list_paginated(self._session, page, size)
        items: list[ResumeListItemDTO] = []
        for resume in resumes:
            latest_analysis = await self._repository.find_latest_analysis(self._session, resume.id)
            items.append(
                ResumeListItemDTO(
                    id=resume.id,
                    filename=resume.original_filename,
                    file_size=resume.file_size,
                    uploaded_at=resume.uploaded_at,
                    access_count=resume.access_count,
                    latest_score=latest_analysis.overall_score if latest_analysis else None,
                    last_analyzed_at=latest_analysis.analyzed_at if latest_analysis else None,
                    interview_count=0,
                    analyze_status=resume.analyze_status,
                    analyze_error=resume.analyze_error,
                )
            )
        return ResumePageDTO(items=items, total=total, page=page, size=size)

    async def get_detail(self, resume_id: int) -> ResumeDetailDTO:
        resume = await self._repository.get_by_id(self._session, resume_id)
        if resume is None:
            raise BusinessException(ErrorCode.RESUME_NOT_FOUND)

        analyses = await self._repository.find_analyses_by_resume_id(self._session, resume_id)
        analysis_dtos = [self._to_analysis_dto(a) for a in analyses]

        return ResumeDetailDTO(
            id=resume.id,
            filename=resume.original_filename,
            file_size=resume.file_size,
            content_type=resume.content_type,
            storage_url=resume.storage_url,
            uploaded_at=resume.uploaded_at,
            access_count=resume.access_count,
            resume_text=resume.resume_text,
            analyze_status=resume.analyze_status,
            analyze_error=resume.analyze_error,
            analyses=analysis_dtos,
        )

    async def delete(self, resume_id: int) -> None:
        resume = await self._repository.get_by_id(self._session, resume_id)
        if resume is None:
            raise BusinessException(ErrorCode.RESUME_NOT_FOUND)

        if resume.storage_key:
            try:
                await self._storage.delete_file(resume.storage_key)
            except Exception as e:
                logger.warning("删除存储文件失败，继续删除数据库记录: resumeId=%s, error=%s", resume_id, e)

        await self._repository.delete_analyses_by_resume_id(self._session, resume_id)
        await self._repository.delete(self._session, resume)
        await self._session.commit()
        logger.info("简历已删除: resumeId=%s", resume_id)

    async def reanalyze(self, resume_id: int) -> None:
        resume = await self._repository.get_by_id(self._session, resume_id)
        if resume is None:
            raise BusinessException(ErrorCode.RESUME_NOT_FOUND)

        await self._repository.update_analyze_status(self._session, resume, AsyncTaskStatus.PENDING.value, None)
        await self._session.commit()
        logger.info("简历重新分析已触发: resumeId=%s", resume_id)
        await self._enqueue_analyze(resume_id)

    async def export_pdf(self, resume_id: int) -> bytes:
        resume = await self._repository.get_by_id(self._session, resume_id)
        if resume is None:
            raise BusinessException(ErrorCode.RESUME_NOT_FOUND)

        analysis = await self._repository.find_latest_analysis(self._session, resume_id)
        if analysis is None:
            raise BusinessException(ErrorCode.RESUME_ANALYSIS_NOT_FOUND)

        return await self._pdf_service.export_resume_analysis(resume, analysis)

    async def _enqueue_analyze(self, resume_id: int) -> None:
        await self._producer.send_task(ResumeAnalyzePayload(resume_id=resume_id))

    def _validate_size(self, data: bytes) -> None:
        if len(data) > self._max_file_size:
            raise BusinessException(
                ErrorCode.RESUME_UPLOAD_FAILED,
                f"文件大小超过限制: {len(data)} > {self._max_file_size}",
            )

    def _is_allowed(self, content_type: str) -> bool:
        return content_type in self._allowed_types

    def _build_duplicate_response(self, resume: Resume) -> ResumeUploadResponse:
        return ResumeUploadResponse(
            resume=self._to_resume_info(resume),
            storage=StorageInfoDTO(
                file_key=resume.storage_key or "",
                file_url=resume.storage_url or "",
                resume_id=resume.id,
            ),
            duplicate=True,
        )

    def _to_resume_info(self, resume: Resume) -> ResumeInfoDTO:
        return ResumeInfoDTO(
            id=resume.id,
            filename=resume.original_filename,
            analyze_status=resume.analyze_status,
        )

    def _to_analysis_dto(self, analysis: ResumeAnalysis) -> AnalysisHistoryDTO:
        strengths_raw = analysis.strengths_json
        suggestions_raw = analysis.suggestions_json
        strengths: list[str] = json.loads(strengths_raw) if strengths_raw else []
        suggestions: list[dict[str, object]] = json.loads(suggestions_raw) if suggestions_raw else []
        return AnalysisHistoryDTO(
            id=analysis.id,
            overall_score=analysis.overall_score,
            content_score=analysis.content_score,
            structure_score=analysis.structure_score,
            skill_match_score=analysis.skill_match_score,
            expression_score=analysis.expression_score,
            project_score=analysis.project_score,
            summary=analysis.summary,
            analyzed_at=analysis.analyzed_at,
            strengths=strengths,
            suggestions=suggestions,
        )
