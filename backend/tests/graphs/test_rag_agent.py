"""Agentic RAG 图单元测试：验证 StateGraph 编译和路由逻辑。"""

from app.graphs.rag_agent import RagAgentGraph, RagAgentState


class TestRagAgentGraphCompile:
    """验证 LangGraph StateGraph 编译成功。"""

    def test_graph_compiles_without_error(self) -> None:
        graph = RagAgentGraph()
        assert graph._compiled is not None


class TestRagAgentRouting:
    """验证路由逻辑。"""

    def test_simple_query_routes_to_direct_search(self) -> None:
        graph = RagAgentGraph()
        state: RagAgentState = {"question": "Redis 缓存", "is_complex": False}
        result = graph._route_complexity(state)
        assert result == "direct_search"

    def test_complex_query_routes_to_decompose(self) -> None:
        graph = RagAgentGraph()
        state: RagAgentState = {"question": "对比 Redis 和 Memcached", "is_complex": True}
        result = graph._route_complexity(state)
        assert result == "decompose"

    def test_quality_ok_routes_to_generate(self) -> None:
        graph = RagAgentGraph()
        state: RagAgentState = {"quality_ok": True, "retry_count": 0}
        result = graph._route_quality(state)
        assert result == "generate_answer"

    def test_quality_low_routes_to_refine(self) -> None:
        graph = RagAgentGraph()
        state: RagAgentState = {"quality_ok": False, "retry_count": 0}
        result = graph._route_quality(state)
        assert result == "refine_query"

    def test_max_retries_forces_generate(self) -> None:
        graph = RagAgentGraph()
        state: RagAgentState = {"quality_ok": False, "retry_count": 2}
        result = graph._route_quality(state)
        assert result == "generate_answer"
