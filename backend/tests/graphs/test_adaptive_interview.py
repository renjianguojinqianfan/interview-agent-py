"""自适应面试 Agent 图单元测试：验证 StateGraph 编译和基本路由逻辑。"""

import logging
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from app.domain.services.adaptive_strategy import (
    compute_strategy_update,
    should_end_interview,
)
from app.graphs.adaptive_interview import _CLEAR, AdaptiveInterviewGraph, _append_or_clear


class TestAdaptiveInterviewGraphCompile:
    """验证 LangGraph StateGraph 编译成功。"""

    def test_graph_compiles_without_error(self) -> None:
        graph = AdaptiveInterviewGraph()
        assert graph._compiled is not None


class TestAdaptiveStrategy:
    """验证策略纯函数逻辑。"""

    def test_no_data_keeps_current(self) -> None:
        result = compute_strategy_update({}, "mid", 0, 6)
        assert result.suggested_difficulty == "mid"
        assert "尚无足够数据" in result.reason

    def test_high_scores_upgrade_difficulty(self) -> None:
        scores = {"JAVA": [8, 9], "MYSQL": [7, 8]}
        result = compute_strategy_update(scores, "mid", 4, 6)
        assert result.suggested_difficulty == "senior"

    def test_low_scores_downgrade_difficulty(self) -> None:
        scores = {"JAVA": [2, 3], "MYSQL": [3, 4]}
        result = compute_strategy_update(scores, "mid", 4, 6)
        assert result.suggested_difficulty == "junior"

    def test_mixed_scores_keep_difficulty(self) -> None:
        scores = {"JAVA": [5, 6], "MYSQL": [6, 5]}
        result = compute_strategy_update(scores, "mid", 3, 6)
        assert result.suggested_difficulty == "mid"

    def test_picks_weakest_category(self) -> None:
        scores = {"JAVA": [8, 9], "MYSQL": [3, 2], "REDIS": [7]}
        result = compute_strategy_update(scores, "mid", 3, 8)
        assert result.suggested_category == "MYSQL"

    def test_should_end_at_max_turns(self) -> None:
        assert should_end_interview(6, 6, {"JAVA": [5, 6], "MYSQL": [5, 6]}) is True


class TestMergeToolResults:
    """HARD #3：并行工具副作用合并必须按 tool_call_index 顺序应用到同一 base。"""

    def _base_state(self) -> dict[str, object]:
        return {
            "qa_history": [
                {
                    "question_index": 0,
                    "question": "Q1",
                    "category": "JAVA",
                    "difficulty": "mid",
                    "answer": "A",
                    "score": None,
                    "feedback": None,
                }
            ],
            "category_scores": {},
            "turn_count": 0,
            "current_category": "JAVA",
            "messages": [],
            "decision_trace": [],
            "tool_messages": [],
            "tool_effects": [],
        }

    async def test_two_evaluate_effects_accumulate_scores_and_turn_count(self) -> None:
        graph = AdaptiveInterviewGraph()
        state = self._base_state()
        state["tool_effects"] = [
            {
                "tool_call_index": 0,
                "side_effect": {
                    "qa_patch": {"question_index": 0, "score": 8, "feedback": "good"},
                    "category_scores_delta": {"JAVA": [8]},
                    "turn_count_delta": 1,
                },
                "trace_entry": {"step": 1, "action": "evaluate_answer"},
            },
            {
                "tool_call_index": 1,
                "side_effect": {
                    "qa_patch": {"question_index": 0, "score": 6, "feedback": "average"},
                    "category_scores_delta": {"JAVA": [6]},
                    "turn_count_delta": 1,
                },
                "trace_entry": {"step": 1, "action": "evaluate_answer"},
            },
        ]

        result = await graph._merge_tool_results(state, {})

        assert result["turn_count"] == 2
        assert result["category_scores"] == {"JAVA": [8, 6]}
        assert result["qa_history"][-1]["score"] == 6
        assert result["qa_history"][-1]["feedback"] == "average"

    async def test_evaluate_and_generate_effects_both_apply(self) -> None:
        graph = AdaptiveInterviewGraph()
        state = self._base_state()
        state["tool_effects"] = [
            {
                "tool_call_index": 0,
                "side_effect": {"current_question": "Q2", "current_category": "MYSQL"},
                "trace_entry": {"step": 1, "action": "generate_question"},
            },
            {
                "tool_call_index": 1,
                "side_effect": {
                    "qa_patch": {"question_index": 0, "score": 9, "feedback": "great"},
                    "category_scores_delta": {"JAVA": [9]},
                    "turn_count_delta": 1,
                },
                "trace_entry": {"step": 1, "action": "evaluate_answer"},
            },
        ]

        result = await graph._merge_tool_results(state, {})

        assert result["current_question"] == "Q2"
        assert result["current_category"] == "MYSQL"
        assert result["category_scores"] == {"JAVA": [9]}
        assert result["turn_count"] == 1
        assert result["qa_history"][-1]["score"] == 9


class TestExecuteSingleToolIndex:
    async def test_tool_effect_carries_tool_call_index(self) -> None:
        graph = AdaptiveInterviewGraph()
        state = {
            "tool_call": {"name": "evaluate_answer", "args": {}, "id": "call_1"},
            "tool_call_index": 3,
            "skill_id": "java-backend",
            "resume_text": "",
            "agent_step_count": 1,
            "difficulty": "mid",
            "current_category": "JAVA",
            "qa_history": [],
            "category_scores": {},
            "turn_count": 0,
        }
        config = {
            "configurable": {
                "chat_client": None,
                "invoker": None,
                "reference_loader": None,
                "llm_registry": None,
                "vector_repository": None,
            }
        }
        with patch.object(
            graph,
            "_dispatch_tool",
            new=AsyncMock(return_value='{"score": 7, "feedback": "ok"}'),
        ):
            result = await graph._execute_single_tool(state, config)

        assert result["tool_effects"][0]["tool_call_index"] == 3


class TestAccumulatorClear:
    """HARD #4：tool_messages/tool_effects 累加器必须能被哨兵清空，避免多轮重复累积。"""

    def test_append_accumulates_messages(self) -> None:
        first = ToolMessage(content="a", tool_call_id="1")
        second = ToolMessage(content="b", tool_call_id="2")

        assert _append_or_clear([first], [second]) == [first, second]

    def test_clear_sentinel_resets_accumulator(self) -> None:
        messages = [ToolMessage(content="a", tool_call_id="1")]

        assert _append_or_clear(messages, _CLEAR) == []

    async def test_merge_returns_clear_sentinel(self) -> None:
        graph = AdaptiveInterviewGraph()
        state = {
            "messages": [],
            "decision_trace": [],
            "tool_messages": [ToolMessage(content="a", tool_call_id="1")],
            "tool_effects": [{"tool_call_index": 0, "side_effect": {}, "trace_entry": {}}],
            "qa_history": [],
            "category_scores": {},
            "turn_count": 0,
        }

        result = await graph._merge_tool_results(state, {})

        assert result["tool_messages"] is _CLEAR
        assert result["tool_effects"] is _CLEAR


class TestStreamFinalState:
    """HARD #7：stream_next_turn 优先从 checkpointer 取权威 final state，否则校验根 output。"""

    async def _events(self, events: list[dict[str, object]]) -> AsyncIterator[dict[str, object]]:
        for event in events:
            yield event

    def _state(self) -> dict[str, object]:
        return {
            "session_id": "s1",
            "qa_history": [
                {
                    "question_index": 0,
                    "question": "Q",
                    "category": "JAVA",
                    "difficulty": "mid",
                    "answer": "A",
                    "score": None,
                    "feedback": None,
                }
            ],
            "messages": [],
            "category_scores": {},
            "turn_count": 0,
            "current_question": None,
            "current_category": "JAVA",
            "finished": False,
            "decision_trace": [],
            "tool_messages": [],
            "tool_effects": [],
        }

    async def _run_stream(
        self, graph: AdaptiveInterviewGraph, state: dict[str, object]
    ) -> list[tuple[str, dict[str, object]]]:
        events: list[tuple[str, dict[str, object]]] = []
        async for event in graph.stream_next_turn(
            chat_client=None,
            invoker=None,
            reference_loader=None,
            llm_registry=None,
            vector_repository=None,
            state=state,
            thread_id="s1",
        ):
            events.append(event)
        return events

    async def test_prefers_checkpointer_state_over_root_output(self) -> None:
        graph = AdaptiveInterviewGraph(checkpointer=MemorySaver())
        state = self._state()
        root_output_state = {**state, "qa_history": [{**state["qa_history"][0], "score": None}]}
        checkpoint_state = {**state, "qa_history": [{**state["qa_history"][0], "score": 8, "feedback": "good"}]}
        graph._compiled.astream_events = lambda *args, **kwargs: self._events(
            [{"event": "on_chain_end", "name": "", "data": {"output": root_output_state}}]
        )
        graph.aget_state = AsyncMock(return_value=checkpoint_state)

        events = await self._run_stream(graph, state)

        final_state = events[-1][1]["state"]
        assert final_state["qa_history"][-1]["score"] == 8
        graph.aget_state.assert_awaited_once_with("s1")

    async def test_falls_back_to_root_output_without_checkpointer(self) -> None:
        graph = AdaptiveInterviewGraph()
        state = self._state()
        root_output_state = {**state, "qa_history": [{**state["qa_history"][0], "score": 7}]}
        graph._compiled.astream_events = lambda *args, **kwargs: self._events(
            [{"event": "on_chain_end", "name": "", "data": {"output": root_output_state}}]
        )

        events = await self._run_stream(graph, state)

        assert events[-1][1]["state"]["qa_history"][-1]["score"] == 7

    async def test_warns_and_falls_back_to_input_when_root_output_missing(
        self,
        caplog: object,
    ) -> None:
        graph = AdaptiveInterviewGraph()
        state = self._state()
        graph._compiled.astream_events = lambda *args, **kwargs: self._events(
            [{"event": "on_chain_start", "name": "agent_loop", "data": {}}]
        )

        with caplog.at_level(logging.WARNING, logger="app.graphs.adaptive_interview"):
            events = await self._run_stream(graph, state)

        assert "回退" in caplog.text
        assert events[-1][1]["state"] is state

    def test_should_not_end_early(self) -> None:
        assert should_end_interview(3, 6, {"JAVA": [5]}) is False

    def test_near_end_with_coverage(self) -> None:
        assert should_end_interview(5, 6, {"JAVA": [5, 6], "MYSQL": [5, 6]}) is True
