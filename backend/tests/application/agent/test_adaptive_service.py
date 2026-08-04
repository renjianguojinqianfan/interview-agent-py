"""自适应面试 Agent 应用服务测试（A5 起，B3 扩展）。"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

from app.application.agent.adaptive_service import AdaptiveInterviewService


class TestStreamAnswerInterrupt:
    async def test_passes_on_interrupt_without_on_result(self) -> None:
        state: dict[str, object] = {
            "session_id": "s1",
            "qa_history": [],
            "category_scores": {},
            "turn_count": 0,
            "difficulty": "mid",
            "current_question": "Q1",
            "current_category": "JAVA",
            "messages": [],
            "finished": False,
            "decision_trace": [],
            "tool_messages": [],
            "tool_effects": [],
        }
        payload = {"question": "Q2", "type": "generate_question_approval"}
        graph = AsyncMock()
        graph.aget_state = AsyncMock(return_value=state)

        async def fake_stream(**kwargs: object) -> AsyncIterator[tuple[str, dict[str, object]]]:
            yield ("on_interrupt", {"payload": payload})

        graph.stream_next_turn = fake_stream
        llm_registry = AsyncMock()
        llm_registry.get_chat_client = AsyncMock(return_value=None)
        service = AdaptiveInterviewService(
            llm_registry=llm_registry,  # type: ignore[arg-type]
            invoker=None,  # type: ignore[arg-type]
            reference_loader=None,  # type: ignore[arg-type]
            vector_repository=None,  # type: ignore[arg-type]
            graph=graph,  # type: ignore[arg-type]
        )

        events = [event async for event in service.stream_answer("s1", "answer")]

        assert events == [{"event": "on_interrupt", "data": {"payload": payload}}]
