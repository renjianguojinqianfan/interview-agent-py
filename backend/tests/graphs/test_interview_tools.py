"""interview_tools 工具契约测试（B1：kb_ids 空值语义）。"""

from types import SimpleNamespace

from app.graphs.tools.interview_tools import agentic_rag_search_impl


class TestAgenticRagSearch:
    async def test_empty_kb_ids_returns_prompt_without_search(self) -> None:
        called = False

        async def fake_query(**kwargs: object) -> dict[str, object]:
            nonlocal called
            called = True
            return {}

        ctx = SimpleNamespace(
            rag_agent_graph=SimpleNamespace(query=fake_query), llm_registry=None, vector_repository=None
        )

        result = await agentic_rag_search_impl("q", [], ctx)  # type: ignore[arg-type]

        assert "未指定" in result
        assert called is False

    async def test_non_empty_kb_ids_searches_with_given_ids(self) -> None:
        captured: dict[str, object] = {}

        async def fake_query(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"answer": "ans", "sources": [{"id": 1}], "retrieval_trace": ["a", "b", "c"]}

        ctx = SimpleNamespace(
            rag_agent_graph=SimpleNamespace(query=fake_query), llm_registry=None, vector_repository=None
        )

        result = await agentic_rag_search_impl("q", [1, 2], ctx)  # type: ignore[arg-type]

        assert captured["kb_ids"] == [1, 2]
        assert "ans" in result
        assert "来源: 1 个文档片段" in result
