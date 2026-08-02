"""自适应面试 LangGraph Agent：ReAct 循环 + Tool Calling + Working Memory。

核心亮点（面试展示）：
- 带回边的 StateGraph（非固定 DAG，真正的 Agent 循环）
- LLM 自主决策调用哪个工具（generate_question / evaluate_answer / lookup_reference）
- 结构化 Working Memory（TypedDict 追踪各维度得分、策略、对话历史）
- 两级降级：单次工具失败 -> 重试或跳过；Agent 整体失败 -> fallback 到兜底题

流程：
START -> init_context -> agent_loop <-> [execute_single_tool (并行) -> merge_tool_results] (循环)
agent_loop -> finalize -> END (当 Agent 决定结束)
"""

import asyncio
import json
import logging
import operator
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any, TypedDict, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from app.domain.services.adaptive_strategy import should_end_interview
from app.graphs.rag_agent import RagAgentGraph
from app.graphs.tools.interview_tools import (
    INTERVIEW_AGENT_TOOLS,
    InterviewToolContext,
    agentic_rag_search_impl,
    evaluate_answer_impl,
    generate_question_impl,
    lookup_reference_impl,
)
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.structured_output import StructuredOutputInvoker
from app.infrastructure.skills.reference_loader import ReferenceLoader
from app.infrastructure.vector.repository import VectorRepository

logger = logging.getLogger(__name__)

_END_SIGNAL = "END_INTERVIEW"
_MAX_AGENT_STEPS = 30  # 安全阀：防止无限循环
_TOOL_TIMEOUT_SECONDS = 60


# ==================== 状态定义 ====================


class QARecord(TypedDict):
    """单轮问答记录。"""

    question_index: int
    question: str
    category: str
    difficulty: str
    answer: str | None
    score: int | None
    feedback: str | None


class AdaptiveInterviewState(TypedDict, total=False):
    """自适应面试 Agent 状态（Working Memory）。"""

    session_id: str
    skill_id: str
    difficulty: str
    resume_text: str
    max_turns: int

    # Working Memory
    qa_history: list[QARecord]
    category_scores: dict[str, list[int]]
    turn_count: int
    current_question: str | None
    current_category: str | None

    # Agent 通信
    messages: list[BaseMessage]
    agent_step_count: int
    finished: bool

    # 最终输出
    final_report: dict[str, Any] | None

    # Agent 决策追踪
    decision_trace: list[dict[str, Any]]
    # {"step": 1, "action": "generate_question", "args": {...}, "result": {...}, "duration_ms": 120}

    # Human-in-the-Loop 审批
    pending_approval: dict[str, Any]  # {"question": "...", "type": "generate_question_approval"}

    # 并行工具执行（Send fan-out 累加器）
    tool_messages: Annotated[list[ToolMessage], operator.add]
    tool_effects: Annotated[list[dict[str, Any]], operator.add]
    # Send fan-out 瞬态载荷（execute_single_tool 节点局部可见）
    tool_call: dict[str, Any]
    tool_call_index: int


# ==================== Config 键 ====================

_CONFIG_CHAT_CLIENT = "chat_client"
_CONFIG_INVOKER = "invoker"
_CONFIG_REFERENCE_LOADER = "reference_loader"
_CONFIG_LLM_REGISTRY = "llm_registry"
_CONFIG_VECTOR_REPO = "vector_repository"


# ==================== Agent 图 ====================


class AdaptiveInterviewGraph:
    """自适应面试 Agent：编译一次，多会话复用。"""

    def __init__(self, checkpointer: Any | None = None, rag_agent: RagAgentGraph | None = None) -> None:
        self._checkpointer = checkpointer
        self._rag_agent = rag_agent or RagAgentGraph()
        self._compiled = self._build()

    async def run_next_turn(
        self,
        chat_client: ChatOpenAI,
        invoker: StructuredOutputInvoker,
        reference_loader: ReferenceLoader,
        llm_registry: LlmProviderRegistry,
        vector_repository: VectorRepository,
        state: AdaptiveInterviewState,
        user_answer: str | None = None,
        thread_id: str | None = None,
    ) -> AdaptiveInterviewState:
        """执行一轮 Agent 循环（提交答案 -> Agent 决策 -> 出题/结束）。

        Args:
            thread_id: 启用 checkpointer 时传入，用于持久化会话状态。
        """
        configurable: dict[str, Any] = {
            _CONFIG_CHAT_CLIENT: chat_client,
            _CONFIG_INVOKER: invoker,
            _CONFIG_REFERENCE_LOADER: reference_loader,
            _CONFIG_LLM_REGISTRY: llm_registry,
            _CONFIG_VECTOR_REPO: vector_repository,
        }
        if thread_id:
            configurable["thread_id"] = thread_id
        config: RunnableConfig = {"configurable": configurable}

        # 如果有用户答案，注入到 messages
        if user_answer is not None:
            state = dict(state)  # type: ignore[assignment]
            user_msg = f"候选人回答了：\n{user_answer}\n\n请先评估这个回答，然后决定下一步。"
            state["messages"] = list(state.get("messages", [])) + [HumanMessage(content=user_msg)]

        result = await self._compiled.ainvoke(state, config=config)
        return cast("AdaptiveInterviewState", result)

    async def resume_turn(
        self,
        chat_client: ChatOpenAI,
        invoker: StructuredOutputInvoker,
        reference_loader: ReferenceLoader,
        llm_registry: LlmProviderRegistry,
        vector_repository: VectorRepository,
        thread_id: str,
        approved: bool,
    ) -> AdaptiveInterviewState:
        """从 interrupt 点恢复 Agent 执行。"""
        configurable: dict[str, Any] = {
            _CONFIG_CHAT_CLIENT: chat_client,
            _CONFIG_INVOKER: invoker,
            _CONFIG_REFERENCE_LOADER: reference_loader,
            _CONFIG_LLM_REGISTRY: llm_registry,
            _CONFIG_VECTOR_REPO: vector_repository,
            "thread_id": thread_id,
        }
        config: RunnableConfig = {"configurable": configurable}
        command: Command[Any] = Command(resume={"approved": approved})
        result = await self._compiled.ainvoke(command, config=config)
        return cast("AdaptiveInterviewState", result)

    async def aget_state(self, thread_id: str) -> AdaptiveInterviewState | None:
        """从 checkpointer 获取指定线程的最新状态。

        当 checkpointer 未启用时返回 None。
        """
        if self._checkpointer is None:
            return None
        snapshot = await self._compiled.aget_state({"configurable": {"thread_id": thread_id}})
        if snapshot is None:
            return None
        return cast("AdaptiveInterviewState", snapshot.values)

    async def stream_next_turn(
        self,
        chat_client: ChatOpenAI,
        invoker: StructuredOutputInvoker,
        reference_loader: ReferenceLoader,
        llm_registry: LlmProviderRegistry,
        vector_repository: VectorRepository,
        state: AdaptiveInterviewState,
        user_answer: str | None = None,
        thread_id: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """流式执行一轮 Agent 循环，yield (event_type, data) 事件。

        事件类型:
        - on_chain_start: 节点开始执行
        - on_chain_end: 节点执行完毕
        - on_llm_stream: LLM 逐 token 输出
        - on_tool_start: 工具开始执行
        - on_tool_end: 工具执行完毕
        - on_final_result: 本轮循环结束，data 包含最终 state
        """
        configurable: dict[str, Any] = {
            _CONFIG_CHAT_CLIENT: chat_client,
            _CONFIG_INVOKER: invoker,
            _CONFIG_REFERENCE_LOADER: reference_loader,
            _CONFIG_LLM_REGISTRY: llm_registry,
            _CONFIG_VECTOR_REPO: vector_repository,
        }
        if thread_id:
            configurable["thread_id"] = thread_id
        config: RunnableConfig = {"configurable": configurable}

        if user_answer is not None:
            state = dict(state)  # type: ignore[assignment]
            user_msg = f"候选人回答了：\n{user_answer}\n\n请先评估这个回答，然后决定下一步。"
            state["messages"] = list(state.get("messages", [])) + [HumanMessage(content=user_msg)]

        # 收集最终 state 用于 on_final_result
        final_state: AdaptiveInterviewState | None = None

        async for event in self._compiled.astream_events(state, config, version="v2"):
            event_name = event["event"]
            name = event.get("name", "")
            data = event.get("data", {})

            if event_name == "on_chain_start" and name in (
                "init_context", "agent_loop", "execute_single_tool", "merge_tool_results", "finalize",
            ):
                yield ("on_chain_start", {"node": name})

            elif event_name == "on_chain_end":
                if name == "finalize":
                    yield ("on_chain_end", {"node": name, "result": "finalize_complete"})
                elif name in (
                    "init_context", "agent_loop", "execute_single_tool", "merge_tool_results",
                ):
                    yield ("on_chain_end", {"node": name})

            elif event_name == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk is not None and hasattr(chunk, "content"):
                    content = chunk.content
                    if isinstance(content, str) and content:
                        yield ("on_llm_stream", {"token": content})

            elif event_name == "on_tool_start":
                tool_input = data.get("input", {})
                yield ("on_tool_start", {"name": name, "args": str(tool_input)[:300]})

            elif event_name == "on_tool_end":
                tool_output = data.get("output", "")
                yield ("on_tool_end", {"name": name, "result": str(tool_output)[:200]})

            # 捕获根 graph 的 output（最终状态快照）
            if event_name == "on_chain_end" and not name:
                output = data.get("output")
                if isinstance(output, dict):
                    final_state = cast(AdaptiveInterviewState, output)

        if final_state is None:
            final_state = state
        yield ("on_final_result", {"state": final_state})

    def _build(self) -> Any:
        builder: StateGraph[AdaptiveInterviewState] = StateGraph(AdaptiveInterviewState)

        builder.add_node("init_context", self._init_context)
        builder.add_node("agent_loop", self._agent_loop)
        builder.add_node("execute_single_tool", self._execute_single_tool)
        builder.add_node("merge_tool_results", self._merge_tool_results)
        builder.add_node("finalize", self._finalize)

        builder.add_edge(START, "init_context")
        builder.add_edge("init_context", "agent_loop")
        builder.add_conditional_edges("agent_loop", self._route_agent_output)
        # execute_single_tool 由 _route_agent_output 通过 Send fan-out 并行启动
        builder.add_edge("execute_single_tool", "merge_tool_results")
        builder.add_edge("merge_tool_results", "agent_loop")  # 回边！构成循环
        builder.add_edge("finalize", END)

        return builder.compile(checkpointer=self._checkpointer)

    # ==================== 节点实现 ====================

    async def _init_context(self, state: AdaptiveInterviewState, config: RunnableConfig) -> dict[str, Any]:
        """初始化 Agent 上下文和 system prompt。"""
        skill_id = state.get("skill_id", "java-backend")
        difficulty = state.get("difficulty", "mid")
        max_turns = state.get("max_turns", 6)
        resume_text = state.get("resume_text", "")
        category_scores = state.get("category_scores", {})

        # 构造 system prompt
        scores_summary = json.dumps(
            {k: f"avg={sum(v) / len(v):.1f}, count={len(v)}" for k, v in category_scores.items()}
            if category_scores
            else {"无数据": "尚未开始"},
            ensure_ascii=False,
        )
        resume_summary = resume_text[:500] + "..." if len(resume_text) > 500 else (resume_text or "未提供简历")

        system_content = f"""你是一位资深面试策略规划者。根据候选人实时表现，自主决定每轮面试行动。

当前面试上下文：
- 技能方向：{skill_id}
- 当前难度：{difficulty}
- 已完成题数：{state.get("turn_count", 0)}/{max_turns}
- 各维度得分：{scores_summary}
- 候选人简历摘要：{resume_summary}

你可以调用工具：generate_question, evaluate_answer, lookup_reference, adjust_strategy。
当面试应该结束时，回复文本 "END_INTERVIEW"（不调用工具）。
如果还没有出第一题，请先调用 generate_question 出一题。"""

        messages = state.get("messages", [])
        if not messages:
            messages = [SystemMessage(content=system_content)]
        else:
            # 更新 system message
            messages = [SystemMessage(content=system_content)] + [
                m for m in messages if not isinstance(m, SystemMessage)
            ]

        return {
            "messages": messages,
            "agent_step_count": 0,
            "finished": False,
            "decision_trace": [
                {
                    "step": 0,
                    "action": "init_context",
                    "args": {"skill_id": skill_id, "difficulty": difficulty, "max_turns": max_turns},
                    "result": {},
                    "duration_ms": 0,
                }
            ],
        }

    async def _agent_loop(self, state: AdaptiveInterviewState, config: RunnableConfig) -> dict[str, Any]:
        """Agent 决策节点：调用 LLM（带 tool binding），决定下一步行动。"""
        chat_client: ChatOpenAI = config["configurable"][_CONFIG_CHAT_CLIENT]
        messages = state.get("messages", [])
        step_count = state.get("agent_step_count", 0)

        # 安全阀
        if step_count >= _MAX_AGENT_STEPS:
            logger.warning("Agent 步数达上限 %d，强制结束", _MAX_AGENT_STEPS)
            return {"finished": True}

        # 强制结束检查
        if should_end_interview(
            state.get("turn_count", 0),
            state.get("max_turns", 6),
            state.get("category_scores", {}),
        ):
            return {"finished": True}

        # 调用 LLM（带工具绑定）
        llm_with_tools = chat_client.bind_tools(INTERVIEW_AGENT_TOOLS)
        try:
            response: AIMessage = await asyncio.wait_for(
                llm_with_tools.ainvoke(messages),
                timeout=_TOOL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning("Agent LLM 决策超时")
            return {"finished": True}
        except Exception as e:
            logger.error("Agent LLM 调用失败: %s", e)
            return {"finished": True}

        # 追加 AI 回复到 messages
        new_messages = list(messages) + [response]
        trace = list(state.get("decision_trace", []))
        tool_calls_info = []
        if response.tool_calls:
            tool_calls_info = [{"name": tc["name"], "args": tc["args"]} for tc in response.tool_calls]
        trace_entry = {
            "step": step_count + 1,
            "action": "agent_loop",
            "args": {"tool_calls": tool_calls_info},
            "result": {},
            "duration_ms": 0,
        }

        # 检查是否要结束
        content = response.content if isinstance(response.content, str) else ""
        if _END_SIGNAL in content:
            decision_trace = trace + [{**trace_entry, "result": {"signal": "END_INTERVIEW"}}]
            return {"messages": new_messages, "finished": True, "decision_trace": decision_trace}

        # 检查是否有 tool calls
        if not response.tool_calls:
            # 没有工具调用也没有结束信号 -> 当作结束
            decision_trace = trace + [{**trace_entry, "result": {"signal": "no_tool_calls"}}]
            return {"messages": new_messages, "finished": True, "decision_trace": decision_trace}

        decision_trace = trace + [trace_entry]
        return {"messages": new_messages, "agent_step_count": step_count + 1, "decision_trace": decision_trace}

    async def _execute_single_tool(
        self,
        state: AdaptiveInterviewState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        """执行单个工具（由 Send fan-out 并行启动）。

        每个 Send 实例携带一个 tool_call，此方法执行该工具并返回结果。
        tool_call_index 用于在合并时保持结果的原始顺序。
        """
        chat_client: ChatOpenAI = config["configurable"][_CONFIG_CHAT_CLIENT]
        invoker: StructuredOutputInvoker = config["configurable"][_CONFIG_INVOKER]
        reference_loader: ReferenceLoader = config["configurable"][_CONFIG_REFERENCE_LOADER]

        tool_call: dict[str, Any] = state["tool_call"]
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call.get("id", "")

        tool_ctx = InterviewToolContext(
            chat_client=chat_client,
            invoker=invoker,
            reference_loader=reference_loader,
            llm_registry=config["configurable"][_CONFIG_LLM_REGISTRY],
            vector_repository=config["configurable"][_CONFIG_VECTOR_REPO],
            rag_agent_graph=self._rag_agent,
            skill_id=state.get("skill_id", "java-backend"),
            resume_text=state.get("resume_text", ""),
        )

        t0 = time.monotonic()
        try:
            result = await self._dispatch_tool(tool_name, tool_args, tool_ctx, state)
            duration_ms = int((time.monotonic() - t0) * 1000)
            tool_message = ToolMessage(content=str(result), tool_call_id=tool_id)

            # 计算副作用
            side_effect = self._apply_tool_side_effects(tool_name, tool_args, result, state)

            trace_entry: dict[str, Any] = {
                "step": state.get("agent_step_count", 0),
                "action": tool_name,
                "args": tool_args,
                "result": str(result)[:200],
                "duration_ms": duration_ms,
            }

            return {
                "tool_messages": [tool_message],
                "tool_effects": [{"side_effect": side_effect, "trace_entry": trace_entry}],
            }

        except Exception as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.warning("Agent 工具执行失败: tool=%s, error=%s", tool_name, e)
            tool_message = ToolMessage(content=f"工具执行失败: {e}", tool_call_id=tool_id)
            error_trace_entry: dict[str, Any] = {
                "step": state.get("agent_step_count", 0),
                "action": tool_name,
                "args": tool_args,
                "result": f"error: {e}",
                "duration_ms": duration_ms,
            }
            return {
                "tool_messages": [tool_message],
                "tool_effects": [{"side_effect": {}, "trace_entry": error_trace_entry}],
            }

    async def _merge_tool_results(
        self,
        state: AdaptiveInterviewState,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        """合并所有并行工具的执行结果，更新 messages 和 Working Memory。

        此节点在 execute_single_tool 全部完成后执行，利用 operator.add reducer
        将 tool_messages 和 tool_effects 合并到 state 中。
        """
        new_messages = list(state.get("messages", []))
        tool_messages = state.get("tool_messages", [])
        tool_effects = state.get("tool_effects", [])
        trace = list(state.get("decision_trace", []))

        # 追加 tool messages 到对话历史
        new_messages.extend(tool_messages)

        # 合并副作用
        merged_effects: dict[str, Any] = {}
        for item in tool_effects:
            side_effect = item.get("side_effect", {})
            trace_entry = item.get("trace_entry", {})
            if trace_entry:
                trace.append(trace_entry)
            for k, v in side_effect.items():
                if k == "qa_history":
                    # qa_history 需要累积
                    existing = merged_effects.get(k, list(state.get("qa_history", [])))
                    merged_effects[k] = v
                elif k == "category_scores":
                    # category_scores 需要合并
                    existing = dict(merged_effects.get(k, state.get("category_scores", {})))
                    for cat, scores in v.items():
                        if cat in existing:
                            existing[cat] = list(existing[cat]) + list(scores)
                        else:
                            existing[cat] = list(scores)
                    merged_effects[k] = existing
                elif k == "turn_count":
                    merged_effects[k] = state.get("turn_count", 0) + 1
                else:
                    merged_effects[k] = v

        return {
            "messages": new_messages,
            "decision_trace": trace,
            "tool_messages": [],  # 清空累加器
            "tool_effects": [],  # 清空累加器
            **merged_effects,
        }

    async def _finalize(self, state: AdaptiveInterviewState, config: RunnableConfig) -> dict[str, Any]:
        """生成最终面试报告。"""
        qa_history = state.get("qa_history", [])
        category_scores = state.get("category_scores", {})

        # 计算总分
        all_scores = [q["score"] for q in qa_history if q.get("score") is not None]
        overall_score = int(sum(s for s in all_scores if s is not None) / len(all_scores)) if all_scores else 0

        report = {
            "session_id": state.get("session_id", ""),
            "total_questions": len(qa_history),
            "overall_score": overall_score,
            "category_scores": {k: int(sum(v) / len(v)) for k, v in category_scores.items() if v},
            "questions": qa_history,
            "difficulty_progression": state.get("difficulty", "mid"),
        }
        trace = list(state.get("decision_trace", []))
        trace.append(
            {
                "step": max((e.get("step", 0) for e in trace), default=0) + 1,
                "action": "finalize",
                "args": {},
                "result": {"total_questions": len(qa_history), "overall_score": overall_score},
                "duration_ms": 0,
            }
        )
        return {"final_report": report, "finished": True, "decision_trace": trace}

    # ==================== 路由函数 ====================

    def _route_agent_output(self, state: AdaptiveInterviewState) -> list[Send] | str:
        """根据 Agent 输出决定走向 execute_single_tool（并行）还是 finalize。

        当 LLM 返回多个 tool_calls 时，通过 Send fan-out 并行执行每个工具。
        """
        if state.get("finished"):
            return "finalize"

        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            tool_calls = messages[-1].tool_calls
            return [
                Send("execute_single_tool", {"tool_call_index": i, "tool_call": tc})
                for i, tc in enumerate(tool_calls)
            ]

        return "finalize"

    # ==================== 工具调度 ====================

    async def _dispatch_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_ctx: InterviewToolContext,
        state: AdaptiveInterviewState,
    ) -> str:
        """根据工具名分发到对应的实现函数。"""
        if tool_name == "generate_question":
            result = await generate_question_impl(
                category=tool_args.get("category", "通用"),
                difficulty=tool_args.get("difficulty", state.get("difficulty", "mid")),
                context=tool_args.get("context", ""),
                tool_ctx=tool_ctx,
            )
            question_json = json.dumps(
                {"question": result.question, "type": result.type, "category": result.category},
                ensure_ascii=False,
            )
            # Human-in-the-Loop：暂停等待人工审批
            approval = interrupt(
                {
                    "question": result.question,
                    "category": result.category,
                    "type": "generate_question_approval",
                    "prompt": "这道题是否合适？",
                }
            )
            if isinstance(approval, dict) and approval.get("approved") is False:
                # 审批不通过，重新生成一题
                logger.info("Agent 出题被驳回，重新生成")
                result = await generate_question_impl(
                    category=tool_args.get("category", "通用"),
                    difficulty=tool_args.get("difficulty", state.get("difficulty", "mid")),
                    context=tool_args.get("context", "") + "\n注意：上一题被驳回，请换一个角度出题。",
                    tool_ctx=tool_ctx,
                )
                question_json = json.dumps(
                    {"question": result.question, "type": result.type, "category": result.category},
                    ensure_ascii=False,
                )
            return question_json

        if tool_name == "evaluate_answer":
            eval_result = await evaluate_answer_impl(
                question=tool_args.get("question", ""),
                answer=tool_args.get("answer", ""),
                category=tool_args.get("category", "通用"),
                tool_ctx=tool_ctx,
            )
            return json.dumps(
                {
                    "score": eval_result.score,
                    "feedback": eval_result.feedback,
                    "shouldFollowUp": eval_result.shouldFollowUp,
                    "followUpSuggestion": eval_result.followUpSuggestion,
                },
                ensure_ascii=False,
            )

        if tool_name == "lookup_reference":
            return await lookup_reference_impl(
                skill_id=tool_args.get("skill_id", tool_ctx.skill_id),
                category=tool_args.get("category", ""),
                tool_ctx=tool_ctx,
            )

        if tool_name == "adjust_strategy":
            from app.domain.services.adaptive_strategy import compute_strategy_update

            strategy_result = compute_strategy_update(
                category_scores=state.get("category_scores", {}),
                current_difficulty=state.get("difficulty", "mid"),
                turn_count=state.get("turn_count", 0),
                max_turns=state.get("max_turns", 6),
            )
            return json.dumps(
                {
                    "suggested_difficulty": strategy_result.suggested_difficulty,
                    "suggested_category": strategy_result.suggested_category,
                    "reason": strategy_result.reason,
                },
                ensure_ascii=False,
            )

        if tool_name == "agentic_rag_search":
            return await agentic_rag_search_impl(
                question=tool_args.get("question", ""),
                kb_ids=tool_args.get("kb_ids", []),
                tool_ctx=tool_ctx,
            )

        return f"未知工具: {tool_name}"

    def _apply_tool_side_effects(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: str,
        state: AdaptiveInterviewState,
    ) -> dict[str, Any]:
        """工具执行后的状态副作用（更新 Working Memory）。"""
        effects: dict[str, Any] = {}

        if tool_name == "generate_question":
            try:
                parsed = json.loads(result)
                effects["current_question"] = parsed.get("question", "")
                effects["current_category"] = parsed.get("category", "通用")
            except (json.JSONDecodeError, TypeError):
                pass

        elif tool_name == "evaluate_answer":
            try:
                parsed = json.loads(result)
                score = parsed.get("score", 0)
                feedback = parsed.get("feedback", "")
                category = state.get("current_category") or "通用"

                # 更新 qa_history
                qa_history = list(state.get("qa_history", []))
                if qa_history and qa_history[-1].get("score") is None:
                    qa_history[-1] = {**qa_history[-1], "score": score, "feedback": feedback}
                effects["qa_history"] = qa_history

                # 更新 category_scores
                category_scores = dict(state.get("category_scores", {}))
                if category not in category_scores:
                    category_scores[category] = []
                category_scores[category] = list(category_scores[category]) + [score]
                effects["category_scores"] = category_scores

                # 更新 turn_count
                effects["turn_count"] = state.get("turn_count", 0) + 1

            except (json.JSONDecodeError, TypeError):
                pass

        elif tool_name == "adjust_strategy":
            try:
                parsed = json.loads(result)
                new_difficulty = parsed.get("suggested_difficulty")
                if new_difficulty and new_difficulty != state.get("difficulty"):
                    effects["difficulty"] = new_difficulty
            except (json.JSONDecodeError, TypeError):
                pass

        return effects
