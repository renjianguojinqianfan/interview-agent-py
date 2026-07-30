from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app.api.deps import get_knowledge_base_service
from app.api.rate_limit import global_key, limiter
from app.api.responses import Result
from app.application.knowledgebase.schemas import (
    KnowledgeBaseDocumentDTO,
    KnowledgeBaseListItemDTO,
    KnowledgeBaseStatsDTO,
    KnowledgeBaseUploadResponse,
    UpdateCategoryRequest,
)
from app.application.knowledgebase.service import KnowledgeBaseService
from app.config.settings import settings

router = APIRouter(prefix="/api/knowledgebase", tags=["知识库管理"])


@router.post("/upload", response_model=Result[KnowledgeBaseUploadResponse])
@limiter.limit("3/second", key_func=global_key)
@limiter.limit("3/second")
async def upload_knowledge_base(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    file: UploadFile = File(...),
    name: str | None = Form(None),
    category: str | None = Form(None),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[KnowledgeBaseUploadResponse]:
    data = await file.read()
    if len(data) > settings.knowledge_base_max_file_size:
        max_mb = settings.knowledge_base_max_file_size // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"文件大小超过限制（最大 {max_mb}MB）")
    filename = file.filename or "unknown"
    content_type = file.content_type or ""
    result = await service.upload(filename, content_type, data, name=name, category=category)
    return Result.success(data=result)


@router.get("/list", response_model=Result[list[KnowledgeBaseListItemDTO]])
async def list_knowledge_bases(
    sort_by: str | None = Query(None, alias="sortBy"),
    vector_status: str | None = Query(None, alias="vectorStatus"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[list[KnowledgeBaseListItemDTO]]:
    data = await service.list_knowledge_bases(sort_by=sort_by, vector_status=vector_status, limit=limit, offset=offset)
    return Result.success(data=data)


@router.get("/stats", response_model=Result[KnowledgeBaseStatsDTO])
async def get_statistics(
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[KnowledgeBaseStatsDTO]:
    data = await service.get_statistics()
    return Result.success(data=data)


@router.get("/categories", response_model=Result[list[str]])
async def list_categories(
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[list[str]]:
    data = await service.list_categories()
    return Result.success(data=data)


@router.get("/category/{category}", response_model=Result[list[KnowledgeBaseListItemDTO]])
async def list_by_category(
    category: str,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[list[KnowledgeBaseListItemDTO]]:
    data = await service.list_by_category(category, limit=limit, offset=offset)
    return Result.success(data=data)


@router.get("/search", response_model=Result[list[KnowledgeBaseListItemDTO]])
async def search_knowledge_bases(
    keyword: str = Query(...),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[list[KnowledgeBaseListItemDTO]]:
    data = await service.search(keyword, limit=limit, offset=offset)
    return Result.success(data=data)


@router.get("/{kb_id}/download")
async def download_knowledge_base(
    kb_id: int,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Response:
    data, filename, content_type = await service.download(kb_id)
    encoded = quote(filename)
    return Response(
        content=data,
        media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@router.put("/{kb_id}/category", response_model=Result[None])
async def update_category(
    kb_id: int,
    body: UpdateCategoryRequest,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[None]:
    await service.update_category(kb_id, body.category)
    return Result.success(data=None)


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: int,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[None]:
    await service.delete(kb_id)
    return Result.success(data=None)


@router.post("/{kb_id}/revectorize")
@limiter.limit("2/second", key_func=global_key)
@limiter.limit("2/second")
async def revectorize_knowledge_base(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    kb_id: int,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[None]:
    await service.revectorize(kb_id)
    return Result.success(data=None)


@router.post("/{kb_id}/documents", response_model=Result[KnowledgeBaseDocumentDTO])
@limiter.limit("3/second", key_func=global_key)
@limiter.limit("3/second")
async def add_knowledge_base_document(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    kb_id: int,
    file: UploadFile = File(...),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[KnowledgeBaseDocumentDTO]:
    """向既有知识库追加文档（ADR-0018，一库多文档）。"""
    data = await file.read()
    if len(data) > settings.knowledge_base_max_file_size:
        max_mb = settings.knowledge_base_max_file_size // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"文件大小超过限制（最大 {max_mb}MB）")
    filename = file.filename or "unknown"
    content_type = file.content_type or ""
    result = await service.add_document(kb_id, filename, content_type, data)
    return Result.success(data=result)


@router.get("/{kb_id}/documents", response_model=Result[list[KnowledgeBaseDocumentDTO]])
async def list_knowledge_base_documents(
    kb_id: int,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[list[KnowledgeBaseDocumentDTO]]:
    data = await service.list_documents(kb_id, limit=limit, offset=offset)
    return Result.success(data=data)


@router.delete("/{kb_id}/documents/{document_id}")
async def delete_knowledge_base_document(
    kb_id: int,
    document_id: int,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[None]:
    await service.delete_document(kb_id, document_id)
    return Result.success(data=None)


# 注册在末尾：避免 /{kb_id} 遮蔽 /list、/stats、/categories、/search 等字面路径（FastAPI 按注册顺序匹配）
@router.get("/{kb_id}", response_model=Result[KnowledgeBaseListItemDTO])
async def get_knowledge_base(
    kb_id: int,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[KnowledgeBaseListItemDTO]:
    data = await service.get_detail(kb_id)
    return Result.success(data=data)
