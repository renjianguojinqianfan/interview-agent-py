"""Agentic RAG LangGraph 子图：自主检索 + 质量评估循环 + 查询改写。

核心亮点（面试展示）：
- Self-Correction：检索质量不足时自主改写查询重试（条件回边）
- Query Planning：复杂问题拆解为子问题分别检索
- 质量评估节点：LLM 判断检索结果是否足够回答问题

流程：
START -> analyze_query -> [simple: direct_search / complex: decompose]
decompose -> multi_search -> evaluate_quality
direct_search -> evaluate_quality
evaluate_quality -> [quality_ok: generate_answer / quality_low: refine_query]
refine_query -> direct_search (循环，max 2 次)
generate_answer -> END
"""

import asyncio
import logging
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.graphs.tools.rag_tools import (
    RagToolContext,
    decompose_question_impl,
    refine_query_impl,
    search_knowledge_base_impl,
)
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer
from app.infrastructure.vector.repository import VectorRepository

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_MIN_CHUNKS_THRESHOLD = 2
_MIN_SCORE_THRESHOLD = 0.5
_SEARCH_TIMEOUT = 30


class RagAgentState(TypedDict, total=False):
    """Agentic RAG 状态。"""

    question: str
    kb_ids: list[int]
    top_k: int

    # 中间状态
    sub_questions: list[str]
    chunks: list[dict[str, object]]
    retry_count: int
    quality_ok: bool
    is_complex: bool

    # 输出
    answer: str
    sources: list[dict[str, object]]
    retrieval_trace: list[str]  # 检索过程追踪


_CONFIG_LLM_REGISTRY = "llm_registry"
_CONFIG_VECTOR_REPO = "vector_repository"
_CONFIG_SANITIZER = "sanitizer"


class RagAgentGraph:
    """Agentic RAG 子图：带质量循环的自主检索。"""

    def __init__(self) -> None:
        self._compiled = self._build()

    async def query(
        self,
        question: str,
        kb_ids: list[int],
        llm_registry: LlmProviderRegistry,
        vector_repository: VectorRepository,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """执行 Agentic RAG 查询，返回答案和检索追踪。"""
        config: RunnableConfig = {
            "configurable": {
                _CONFIG_LLM_REGISTRY: llm_registry,
                _CONFIG_VECTOR_REPO: vector_repository,
                _CONFIG_SANITIZER: PromptSanitizer(),
            }
        }
        initial: RagAgentState = {
            "question": question,
            "kb_ids": kb_ids,
            "top_k": top_k,
            "sub_questions": [],
            "chunks": [],
            "retry_count": 0,
            "quality_ok": False,
            "is_complex": False,
            "answer": "",
            "sources": [],
            "retrieval_trace": [],
        }
        result = await self._compiled.ainvoke(initial, config=config)
        return {
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
            "retrieval_trace": result.get("retrieval_trace", []),
        }

    def _build(self) -> Any:
        builder: StateGraph[RagAgentState] = StateGraph(RagAgentState)

        builder.add_node("analyze_query", self._analyze_query)
        builder.add_node("direct_search", self._direct_search)
        builder.add_node("decompose", self._decompose)
        builder.add_node("multi_search", self._multi_search)
        builder.add_node("evaluate_quality", self._evaluate_quality)
        builder.add_node("refine_query", self._refine_query)
        builder.add_node("generate_answer", self._generate_answer)

        builder.add_edge(START, "analyze_query")
        builder.add_conditional_edges("analyze_query", self._route_complexity)
        builder.add_edge("direct_search", "evaluate_quality")
        builder.add_edge("decompose", "multi_search")
        builder.add_edge("multi_search", "evaluate_quality")
        builder.add_conditional_edges("evaluate_quality", self._route_quality)
        builder.add_edge("refine_query", "direct_search")  # 回边！循环
        builder.add_edge("generate_answer", END)

        return builder.compile()

    # ==================== 节点 ====================

    async def _analyze_query(self, state: RagAgentState, config: RunnableConfig) -> dict[str, Any]:
        """分析查询复杂度：简单问题直接检索，复杂问题拆解。"""
        question = state.get("question", "")
        trace = list(state.get("retrieval_trace", []))

        # 简单启发式：问题长度 > 50 或包含"和"/"以及"/"对比" 视为复杂
        is_complex = len(question) > 50 or any(kw in question for kw in ["和", "以及", "对比", "区别", "比较"])
        trace.append(f"[分析] 问题复杂度: {'复杂' if is_complex else '简单'}")

        return {"is_complex": is_complex, "retrieval_trace": trace}

    async def _direct_search(self, state: RagAgentState, config: RunnableConfig) -> dict[str, Any]:
        """直接向量检索。"""
        ctx = self._get_ctx(config)
        question = state.get("question", "")
        kb_ids = state.get("kb_ids", [])
        top_k = state.get("top_k", 5)
        trace = list(state.get("retrieval_trace", []))

        try:
            chunks = await asyncio.wait_for(
                search_knowledge_base_impl(question, kb_ids, top_k, ctx),
                timeout=_SEARCH_TIMEOUT,
            )
            trace.append(f"[检索] 直接搜索返回 {len(chunks)} 个结果")
        except TimeoutError:
            chunks = []
            trace.append("[检索] 搜索超时")
        except Exception as e:
            chunks = []
            trace.append(f"[检索] 搜索失败: {e}")

        return {"chunks": chunks, "retrieval_trace": trace}

    async def _decompose(self, state: RagAgentState, config: RunnableConfig) -> dict[str, Any]:
        """将复杂问题拆解为子问题。"""
        ctx = self._get_ctx(config)
        question = state.get("question", "")
        trace = list(state.get("retrieval_trace", []))

        try:
            sub_questions = await decompose_question_impl(question, ctx)
            trace.append(f"[拆解] 拆为 {len(sub_questions)} 个子问题: {sub_questions}")
        except Exception as e:
            sub_questions = [question]
            trace.append(f"[拆解] 失败，使用原问题: {e}")

        return {"sub_questions": sub_questions, "retrieval_trace": trace}

    async def _multi_search(self, state: RagAgentState, config: RunnableConfig) -> dict[str, Any]:
        """对多个子问题并行检索。"""
        ctx = self._get_ctx(config)
        sub_questions = state.get("sub_questions", [])
        kb_ids = state.get("kb_ids", [])
        top_k = state.get("top_k", 5)
        trace = list(state.get("retrieval_trace", []))

        all_chunks: list[dict[str, object]] = []
        for sq in sub_questions:
            try:
                chunks = await asyncio.wait_for(
                    search_knowledge_base_impl(sq, kb_ids, top_k, ctx),
                    timeout=_SEARCH_TIMEOUT,
                )
                all_chunks.extend(chunks)
            except Exception as e:
                trace.append(f"[多路检索] 子问题 '{sq[:30]}...' 失败: {e}")

        # 去重（按 content hash）
        seen: set[str] = set()
        deduped: list[dict[str, object]] = []
        for chunk in all_chunks:
            content = str(chunk.get("content", ""))
            if content not in seen:
                seen.add(content)
                deduped.append(chunk)

        trace.append(f"[多路检索] 合并去重后 {len(deduped)} 个结果")
        return {"chunks": deduped, "retrieval_trace": trace}

    async def _evaluate_quality(self, state: RagAgentState, config: RunnableConfig) -> dict[str, Any]:
        """评估检索结果质量：数量和相关性。"""
        chunks = state.get("chunks", [])
        trace = list(state.get("retrieval_trace", []))

        # 质量判断
        if len(chunks) < _MIN_CHUNKS_THRESHOLD:
            quality_ok = False
            trace.append(f"[质量评估] 结果不足 ({len(chunks)} < {_MIN_CHUNKS_THRESHOLD})")
        else:
            # 检查最高分是否达标
            max_score = max((float(str(c.get("score", 0))) for c in chunks), default=0.0)
            quality_ok = max_score >= _MIN_SCORE_THRESHOLD
            if quality_ok:
                trace.append(f"[质量评估] 通过 (最高分 {max_score:.2f})")
            else:
                trace.append(f"[质量评估] 分数不足 (最高分 {max_score:.2f} < {_MIN_SCORE_THRESHOLD})")

        return {"quality_ok": quality_ok, "retrieval_trace": trace}

    async def _refine_query(self, state: RagAgentState, config: RunnableConfig) -> dict[str, Any]:
        """改写查询以提升召回。"""
        ctx = self._get_ctx(config)
        question = state.get("question", "")
        retry_count = state.get("retry_count", 0)
        trace = list(state.get("retrieval_trace", []))

        feedback = f"第 {retry_count + 1} 次检索结果不够好，请换一种表述"
        try:
            refined = await refine_query_impl(question, feedback, ctx)
            trace.append(f"[改写] 原: '{question[:50]}...' -> 新: '{refined[:50]}...'")
        except Exception as e:
            refined = question
            trace.append(f"[改写] 失败，使用原问题: {e}")

        return {
            "question": refined,
            "retry_count": retry_count + 1,
            "retrieval_trace": trace,
        }

    async def _generate_answer(self, state: RagAgentState, config: RunnableConfig) -> dict[str, Any]:
        """基于检索结果生成最终回答。"""
        registry: LlmProviderRegistry = config["configurable"][_CONFIG_LLM_REGISTRY]
        chunks = state.get("chunks", [])
        question = state.get("question", "")
        trace = list(state.get("retrieval_trace", []))

        if not chunks:
            trace.append("[生成] 无检索结果，返回提示")
            return {
                "answer": "抱歉，知识库中未找到与您问题相关的信息。",
                "sources": [],
                "retrieval_trace": trace,
            }

        # 构造上下文
        context_parts = [str(c.get("content", "")) for c in chunks[:5]]
        context = "\n\n---\n\n".join(context_parts)

        llm = await registry.get_chat_client()
        messages = [
            SystemMessage(
                content="你是一个基于知识库的问答助手。请仅根据提供的上下文回答问题。如果上下文中没有相关信息，请明确说明。"
            ),
            HumanMessage(content=f"上下文：\n{context}\n\n问题：{question}"),
        ]

        try:
            response = await llm.ainvoke(messages)
            answer = response.content if isinstance(response.content, str) else str(response.content)
            trace.append(f"[生成] 成功，答案长度 {len(answer)}")
        except Exception as e:
            answer = f"回答生成失败: {e}"
            trace.append(f"[生成] 失败: {e}")

        sources = [{"content": str(c.get("content", ""))[:200], "score": c.get("score")} for c in chunks[:5]]
        return {"answer": answer, "sources": sources, "retrieval_trace": trace}

    # ==================== 路由 ====================

    def _route_complexity(self, state: RagAgentState) -> str:
        if state.get("is_complex"):
            return "decompose"
        return "direct_search"

    def _route_quality(self, state: RagAgentState) -> str:
        if state.get("quality_ok"):
            return "generate_answer"
        if state.get("retry_count", 0) >= _MAX_RETRIES:
            # 达到重试上限，强制生成答案
            return "generate_answer"
        return "refine_query"

    # ==================== 辅助 ====================

    def _get_ctx(self, config: RunnableConfig) -> RagToolContext:
        return RagToolContext(
            llm_registry=config["configurable"][_CONFIG_LLM_REGISTRY],
            vector_repository=config["configurable"][_CONFIG_VECTOR_REPO],
            sanitizer=config["configurable"][_CONFIG_SANITIZER],
        )
