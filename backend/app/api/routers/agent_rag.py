"""Agentic RAG API 路由：独立于现有 RAG 问答，展示 Self-Correction 检索循环。"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_agentic_rag_service
from app.api.responses import Result
from app.application.agent.agentic_rag_service import AgenticRagService


class AgentRagQueryRequest(BaseModel):
    """Agentic RAG 查询请求。"""

    question: str
    knowledge_base_ids: list[int] = Field(alias="knowledgeBaseIds")
    top_k: int = 5

    model_config = {"populate_by_name": True}


class AgentRagQueryResponse(BaseModel):
    """Agentic RAG 查询响应。"""

    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_trace: list[str] = Field(default_factory=list)


router = APIRouter(prefix="/api/agent/rag", tags=["Agentic RAG"])


@router.post("/query", response_model=Result[AgentRagQueryResponse])
async def agent_rag_query(
    body: AgentRagQueryRequest,
    service: AgenticRagService = Depends(get_agentic_rag_service),
) -> Result[AgentRagQueryResponse]:
    """Agentic RAG 查询（非流式）。返回答案 + 完整检索过程追踪。"""
    result = await service.query(
        question=body.question,
        kb_ids=body.knowledge_base_ids,
        top_k=body.top_k,
    )
    return Result.success(
        data=AgentRagQueryResponse(
            answer=result["answer"],
            sources=result.get("sources", []),
            retrieval_trace=result.get("retrieval_trace", []),
        )
    )
