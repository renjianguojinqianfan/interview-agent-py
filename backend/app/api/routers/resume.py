from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app.api.deps import get_resume_service
from app.api.rate_limit import global_key, limiter
from app.api.responses import Result
from app.application.resume.schemas import (
    ResumeDetailDTO,
    ResumeListItemDTO,
    ResumeStatsDTO,
    ResumeUploadResponse,
)
from app.application.resume.service import ResumeService
from app.config.settings import settings

router = APIRouter(prefix="/api/resumes", tags=["简历管理"])


@router.post("/upload", response_model=Result[ResumeUploadResponse])
@limiter.limit("5/second", key_func=global_key)
@limiter.limit("5/second")
async def upload_resume(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    file: UploadFile = File(...),
    service: ResumeService = Depends(get_resume_service),
) -> Result[ResumeUploadResponse]:
    data = await file.read()
    if len(data) > settings.resume_max_file_size:
        max_mb = settings.resume_max_file_size // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"文件大小超过限制（最大 {max_mb}MB）")
    filename = file.filename or "unknown"
    content_type = file.content_type or ""
    result = await service.upload(filename, content_type, data)
    return Result.success(data=result)


@router.get("", response_model=Result[list[ResumeListItemDTO]])
async def list_resumes(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: ResumeService = Depends(get_resume_service),
) -> Result[list[ResumeListItemDTO]]:
    result = await service.list_resumes(limit=limit, offset=offset)
    return Result.success(data=result)


@router.get("/statistics", response_model=Result[ResumeStatsDTO])
async def get_resume_statistics(
    service: ResumeService = Depends(get_resume_service),
) -> Result[ResumeStatsDTO]:
    result = await service.get_statistics()
    return Result.success(data=result)


@router.get("/{resume_id}/detail", response_model=Result[ResumeDetailDTO])
async def get_resume_detail(
    resume_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> Result[ResumeDetailDTO]:
    result = await service.get_detail(resume_id)
    return Result.success(data=result)


@router.delete("/{resume_id}")
async def delete_resume(
    resume_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> Result[None]:
    await service.delete(resume_id)
    return Result.success(data=None)


@router.post("/{resume_id}/reanalyze")
@limiter.limit("2/second", key_func=global_key)
@limiter.limit("2/second")
async def reanalyze_resume(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    resume_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> Result[None]:
    await service.reanalyze(resume_id)
    return Result.success(data=None)


@router.get("/{resume_id}/export")
async def export_resume_pdf(
    resume_id: int,
    service: ResumeService = Depends(get_resume_service),
) -> Response:
    pdf_bytes = await service.export_pdf(resume_id)
    filename = f"resume_{resume_id}_analysis.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
