"""Agentic RAG 工具：search_knowledge_base / refine_query / decompose_question。

供 rag_agent.py 的质量循环图节点调用。复用现有 vector_repository + llm_registry 基础设施。
"""

import logging
from dataclasses import dataclass

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer
from app.infrastructure.vector.repository import VectorRepository

logger = logging.getLogger(__name__)


@dataclass
class RagToolContext:
    """RAG 工具运行时上下文（通过 RunnableConfig 传递）。"""

    llm_registry: LlmProviderRegistry
    vector_repository: VectorRepository
    sanitizer: PromptSanitizer


# ==================== 工具实现 ====================


async def search_knowledge_base_impl(
    query: str,
    kb_ids: list[int],
    top_k: int,
    ctx: RagToolContext,
) -> list[dict[str, object]]:
    """向量检索指定知识库，返回 chunk 列表。"""

    from app.infrastructure.db.session import async_session_factory

    embeddings = await ctx.llm_registry.get_default_embeddings()
    vectors = await embeddings.aembed_documents([query])
    if not vectors:
        return []

    async with async_session_factory() as session:
        results = await ctx.vector_repository.search(session, vectors[0], kb_ids, top_k)

    return [{"content": r.content, "score": r.score, "kb_id": r.kb_id} for r in results]


async def refine_query_impl(
    original_query: str,
    feedback: str,
    ctx: RagToolContext,
) -> str:
    """LLM 改写查询以提升检索召回率。"""
    from langchain_core.messages import HumanMessage

    llm = await ctx.llm_registry.get_chat_client()
    prompt = f"""你是一个搜索查询优化专家。用户的原始问题检索效果不好，请改写为更适合向量检索的查询。

原始问题：{ctx.sanitizer.sanitize(original_query)}
检索反馈：{feedback}

请直接返回改写后的查询文本（一句话，不要解释）："""
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    content = response.content if isinstance(response.content, str) else str(response.content)
    return content.strip() or original_query


async def decompose_question_impl(
    complex_query: str,
    ctx: RagToolContext,
) -> list[str]:
    """将复杂问题拆解为多个子问题，分别检索。"""
    from langchain_core.messages import HumanMessage

    llm = await ctx.llm_registry.get_chat_client()
    prompt = f"""你是一个问题分解专家。请将以下复杂问题拆解为 2-3 个独立的子问题，每个子问题更适合向量检索。

复杂问题：{ctx.sanitizer.sanitize(complex_query)}

请每行返回一个子问题（不要编号，不要解释）："""
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    content = response.content if isinstance(response.content, str) else str(response.content)
    sub_questions = [q.strip() for q in content.strip().split("\n") if q.strip()]
    return sub_questions[:3] if sub_questions else [complex_query]


# ==================== 工具参数 Schemas ====================


class SearchKnowledgeBaseArgs(BaseModel):
    """向量检索知识库。"""

    query: str = Field(description="搜索查询文本")
    kb_ids: str = Field(default="", description="知识库 ID 列表（逗号分隔）")
    top_k: int = Field(default=5, description="返回结果数量上限")


class RefineQueryArgs(BaseModel):
    """改写搜索查询以提升检索质量。"""

    original_query: str = Field(description="原始用户问题")
    feedback: str = Field(description="为什么当前检索结果不好的原因描述")


class DecomposeQuestionArgs(BaseModel):
    """将复杂问题拆解为多个子问题。"""

    complex_query: str = Field(description="需要拆解的复杂问题")


# ==================== StructuredTool 定义（供 Agent bind_tools） ====================
# 不传 func → 直接调用会报错，防止误调时静默返回占位字符串

search_knowledge_base_tool = StructuredTool(
    name="search_knowledge_base",
    description="向量检索知识库。返回最相关的文档片段。",
    args_schema=SearchKnowledgeBaseArgs,
)

refine_query_tool = StructuredTool(
    name="refine_query",
    description="改写搜索查询以提升检索质量。当检索结果不够好时调用。",
    args_schema=RefineQueryArgs,
)

decompose_question_tool = StructuredTool(
    name="decompose_question",
    description="将复杂问题拆解为多个子问题。当问题涉及多个方面时调用。",
    args_schema=DecomposeQuestionArgs,
)


RAG_AGENT_TOOLS = [search_knowledge_base_tool, refine_query_tool, decompose_question_tool]
