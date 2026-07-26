"""知识库面试路由：题库管理端点（issue #42）。

新端点集中于此文件（#43 生成、#44 组卷面试后续同文件追加）；
GET /api/knowledgebase/{id} 详情补进现有 knowledgebase 路由。
路径对齐 Java KnowledgeBaseInterviewController 与前端 knowledgebase.ts。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_knowledge_base_question_service
from app.api.rate_limit import global_key, limiter
from app.api.responses import Result
from app.application.knowledgebase.question_schemas import (
    CategoryCountDTO,
    CreateKnowledgeBaseQuestionRequest,
    GenerateKnowledgeBaseQuestionsRequest,
    KnowledgeBaseQuestionDTO,
    QuestionGenStatusResponse,
    UpdateKnowledgeBaseQuestionRequest,
    UpdateKnowledgeBaseQuestionStatusRequest,
)
from app.application.knowledgebase.question_service import KnowledgeBaseQuestionService

router = APIRouter(tags=["知识库面试"])

_StatusFilter = Literal["DRAFT", "ACTIVE", "ARCHIVED", "STALE"]


@router.get("/api/knowledgebase/{kb_id}/questions", response_model=Result[list[KnowledgeBaseQuestionDTO]])
async def list_questions(
    kb_id: int,
    status: _StatusFilter | None = Query(None),
    category: str | None = Query(None),
    difficulty: str | None = Query(None),
    keyword: str | None = Query(None),
    service: KnowledgeBaseQuestionService = Depends(get_knowledge_base_question_service),
) -> Result[list[KnowledgeBaseQuestionDTO]]:
    data = await service.list_questions(kb_id, status, category, difficulty, keyword)
    return Result.success(data=data)


@router.get("/api/knowledgebase/{kb_id}/questions/categories", response_model=Result[list[CategoryCountDTO]])
async def list_question_categories(
    kb_id: int,
    service: KnowledgeBaseQuestionService = Depends(get_knowledge_base_question_service),
) -> Result[list[CategoryCountDTO]]:
    data = await service.list_categories(kb_id)
    return Result.success(data=data)


@router.post("/api/knowledgebase/{kb_id}/questions/generate", response_model=Result[QuestionGenStatusResponse])
@limiter.limit("2/second", key_func=global_key)
@limiter.limit("2/second")
async def generate_questions(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    kb_id: int,
    body: GenerateKnowledgeBaseQuestionsRequest,
    service: KnowledgeBaseQuestionService = Depends(get_knowledge_base_question_service),
) -> Result[QuestionGenStatusResponse]:
    data = await service.submit_generation_task(kb_id, body)
    return Result.success(data=data)


@router.get(
    "/api/knowledgebase/{kb_id}/questions/generation-status",
    response_model=Result[QuestionGenStatusResponse],
)
async def get_question_generation_status(
    kb_id: int,
    service: KnowledgeBaseQuestionService = Depends(get_knowledge_base_question_service),
) -> Result[QuestionGenStatusResponse]:
    data = await service.get_generation_status(kb_id)
    return Result.success(data=data)


@router.post("/api/knowledgebase/{kb_id}/questions", response_model=Result[KnowledgeBaseQuestionDTO])
async def create_question(
    kb_id: int,
    body: CreateKnowledgeBaseQuestionRequest,
    service: KnowledgeBaseQuestionService = Depends(get_knowledge_base_question_service),
) -> Result[KnowledgeBaseQuestionDTO]:
    data = await service.create_question(kb_id, body)
    return Result.success(data=data)


@router.put("/api/knowledgebase/questions/{question_id}", response_model=Result[KnowledgeBaseQuestionDTO])
async def update_question(
    question_id: int,
    body: UpdateKnowledgeBaseQuestionRequest,
    service: KnowledgeBaseQuestionService = Depends(get_knowledge_base_question_service),
) -> Result[KnowledgeBaseQuestionDTO]:
    data = await service.update_question(question_id, body)
    return Result.success(data=data)


@router.put("/api/knowledgebase/questions/{question_id}/status", response_model=Result[KnowledgeBaseQuestionDTO])
async def update_question_status(
    question_id: int,
    body: UpdateKnowledgeBaseQuestionStatusRequest,
    service: KnowledgeBaseQuestionService = Depends(get_knowledge_base_question_service),
) -> Result[KnowledgeBaseQuestionDTO]:
    data = await service.update_status(question_id, body.status)
    return Result.success(data=data)


@router.delete("/api/knowledgebase/questions/{question_id}", response_model=Result[None])
async def delete_question(
    question_id: int,
    service: KnowledgeBaseQuestionService = Depends(get_knowledge_base_question_service),
) -> Result[None]:
    await service.delete_question(question_id)
    return Result.success(data=None)
