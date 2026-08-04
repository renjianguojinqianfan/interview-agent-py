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


class TestPendingApprovalExposure:
    def _state(self, pending_approval: object = None) -> dict[str, object]:
        return {
            "session_id": "s1",
            "skill_id": "java-backend",
            "difficulty": "mid",
            "turn_count": 0,
            "max_turns": 6,
            "current_question": "Q1",
            "current_category": "JAVA",
            "finished": False,
            "category_scores": {},
            "decision_trace": [],
            "qa_history": [],
            "pending_approval": pending_approval,
        }

    async def test_get_session_exposes_pending_approval(self) -> None:
        payload = {"question": "Q2", "type": "generate_question_approval"}
        graph = AsyncMock()
        graph.aget_state = AsyncMock(return_value=self._state(payload))
        service = AdaptiveInterviewService(
            llm_registry=AsyncMock(),  # type: ignore[arg-type]
            invoker=None,  # type: ignore[arg-type]
            reference_loader=None,  # type: ignore[arg-type]
            vector_repository=None,  # type: ignore[arg-type]
            graph=graph,  # type: ignore[arg-type]
        )

        dto = await service.get_session("s1")

        assert dto.pending_approval == payload

    async def test_resume_result_clears_pending_approval(self) -> None:
        from app.application.agent.schemas import ResumeSessionRequest

        state = self._state(None)
        graph = AsyncMock()
        graph.aget_state = AsyncMock(return_value=state)

        async def fake_resume(**kwargs: object) -> dict[str, object]:
            return state

        graph.resume_turn = fake_resume
        llm_registry = AsyncMock()
        llm_registry.get_chat_client = AsyncMock(return_value=None)
        service = AdaptiveInterviewService(
            llm_registry=llm_registry,  # type: ignore[arg-type]
            invoker=None,  # type: ignore[arg-type]
            reference_loader=None,  # type: ignore[arg-type]
            vector_repository=None,  # type: ignore[arg-type]
            graph=graph,  # type: ignore[arg-type]
        )

        result = await service.resume_session("s1", ResumeSessionRequest())

        assert result.pending_approval is None
