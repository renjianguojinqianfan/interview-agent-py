"""Agentic RAG 应用服务：编排 RagAgentGraph，提供独立的 Agent RAG 查询能力。"""

import logging
from typing import Any

from app.graphs.rag_agent import RagAgentGraph
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.vector.repository import VectorRepository

logger = logging.getLogger(__name__)


class AgenticRagService:
    """Agentic RAG 服务：带质量循环的自主检索。"""

    def __init__(
        self,
        llm_registry: LlmProviderRegistry,
        vector_repository: VectorRepository,
        graph: RagAgentGraph,
    ) -> None:
        self._llm_registry = llm_registry
        self._vector_repository = vector_repository
        self._graph = graph

    async def query(self, question: str, kb_ids: list[int], top_k: int = 5) -> dict[str, Any]:
        """执行 Agentic RAG 查询。

        返回:
            {"answer": str, "sources": list, "retrieval_trace": list}
        """
        if not question.strip():
            return {"answer": "请输入问题", "sources": [], "retrieval_trace": []}
        if not kb_ids:
            return {"answer": "请至少选择一个知识库", "sources": [], "retrieval_trace": []}

        try:
            return await self._graph.query(
                question=question,
                kb_ids=kb_ids,
                llm_registry=self._llm_registry,
                vector_repository=self._vector_repository,
                top_k=top_k,
            )
        except Exception as e:
            logger.error("Agentic RAG 查询失败: %s", e)
            return {
                "answer": f"查询失败: {e}",
                "sources": [],
                "retrieval_trace": [f"[错误] {e}"],
            }
