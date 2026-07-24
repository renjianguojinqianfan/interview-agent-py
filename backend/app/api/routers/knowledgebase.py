from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response

from app.api.deps import get_knowledge_base_service
from app.api.rate_limit import global_key, limiter
from app.api.responses import Result
from app.application.knowledgebase.schemas import (
    KnowledgeBaseListItemDTO,
    KnowledgeBaseStatsDTO,
    KnowledgeBaseUploadResponse,
    UpdateCategoryRequest,
)
from app.application.knowledgebase.service import KnowledgeBaseService

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
    filename = file.filename or "unknown"
    content_type = file.content_type or ""
    result = await service.upload(filename, content_type, data, name=name, category=category)
    return Result.success(data=result)


@router.get("/list", response_model=Result[list[KnowledgeBaseListItemDTO]])
async def list_knowledge_bases(
    sort_by: str | None = Query(None, alias="sortBy"),
    vector_status: str | None = Query(None, alias="vectorStatus"),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[list[KnowledgeBaseListItemDTO]]:
    data = await service.list_knowledge_bases(sort_by=sort_by, vector_status=vector_status)
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
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[list[KnowledgeBaseListItemDTO]]:
    data = await service.list_by_category(category)
    return Result.success(data=data)


@router.get("/search", response_model=Result[list[KnowledgeBaseListItemDTO]])
async def search_knowledge_bases(
    keyword: str = Query(...),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[list[KnowledgeBaseListItemDTO]]:
    data = await service.search(keyword)
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
