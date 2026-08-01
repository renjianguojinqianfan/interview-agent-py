"""自适应面试 Agent 应用服务：编排 LangGraph Agent 循环，管理内存会话状态。

不依赖 session_service.py，完全独立的 Agent 面试流程。
会话状态暂存内存（dict），生产环境可升级为 Redis / LangGraph Checkpointer。
"""

import logging
import uuid
from collections import OrderedDict

from app.application.agent.schemas import (
    AdaptiveAnswerResultDTO,
    AdaptiveQuestionDTO,
    AdaptiveReportDTO,
    AdaptiveSessionDTO,
    CreateAdaptiveSessionRequest,
)
from app.domain.errors import BusinessException, ErrorCode
from app.graphs.adaptive_interview import AdaptiveInterviewGraph, AdaptiveInterviewState, QARecord
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.structured_output import StructuredOutputInvoker
from app.infrastructure.skills.reference_loader import ReferenceLoader

logger = logging.getLogger(__name__)

_MAX_SESSIONS = 500
"""内存会话容量上限，超出后淘汰最久未访问的会话。"""


class AdaptiveInterviewService:
    """自适应面试 Agent 应用服务。

    管理内存中的会话状态，调用 AdaptiveInterviewGraph 驱动每轮 Agent 循环。
    """

    def __init__(
        self,
        llm_registry: LlmProviderRegistry,
        invoker: StructuredOutputInvoker,
        reference_loader: ReferenceLoader,
        graph: AdaptiveInterviewGraph,
    ) -> None:
        self._llm_registry = llm_registry
        self._invoker = invoker
        self._reference_loader = reference_loader
        self._graph = graph
        # 内存会话存储（LRU 淘汰，生产可换 Redis）
        self._sessions: OrderedDict[str, AdaptiveInterviewState] = OrderedDict()

    async def create_session(self, request: CreateAdaptiveSessionRequest) -> AdaptiveSessionDTO:
        """创建自适应面试会话并触发 Agent 生成第一题。"""
        session_id = uuid.uuid4().hex[:16]

        # 初始化状态
        state: AdaptiveInterviewState = {
            "session_id": session_id,
            "skill_id": request.skill_id,
            "difficulty": request.difficulty,
            "resume_text": request.resume_text,
            "max_turns": request.max_turns,
            "qa_history": [],
            "category_scores": {},
            "turn_count": 0,
            "current_question": None,
            "current_category": None,
            "messages": [],
            "agent_step_count": 0,
            "finished": False,
            "final_report": None,
            "decision_trace": [],
        }

        # 获取 LLM 客户端
        provider_id = None
        if request.llm_provider:
            provider_id = await self._llm_registry.resolve_provider_id_by_name(request.llm_provider)
        chat_client = await self._llm_registry.get_chat_client(provider_id)

        # 运行 Agent 首轮（生成第一题）
        state = await self._graph.run_next_turn(
            chat_client=chat_client,
            invoker=self._invoker,
            reference_loader=self._reference_loader,
            state=state,
            user_answer=None,
        )

        self._put_state(session_id, state)
        logger.info("创建自适应面试会话: sessionId=%s, skill=%s", session_id, request.skill_id)
        return self._to_session_dto(state)

    async def get_session(self, session_id: str) -> AdaptiveSessionDTO:
        """获取会话当前状态。"""
        state = self._get_state(session_id)
        return self._to_session_dto(state)

    async def submit_answer(self, session_id: str, answer: str) -> AdaptiveAnswerResultDTO:
        """提交答案，触发 Agent 评估 + 出下一题。"""
        state = self._get_state(session_id)
        if state.get("finished"):
            raise BusinessException(ErrorCode.INTERVIEW_ALREADY_COMPLETED, "面试已结束")

        # 操作副本，graph 成功后再写回（防止异常时脏数据残留）
        working_state: AdaptiveInterviewState = {**state}
        qa_history: list[QARecord] = list(working_state.get("qa_history", []))
        current_q = working_state.get("current_question") or ""
        current_cat = working_state.get("current_category") or "通用"
        qa_history.append(
            {
                "question_index": working_state.get("turn_count", 0),
                "question": current_q,
                "category": current_cat,
                "difficulty": working_state.get("difficulty", "mid"),
                "answer": answer,
                "score": None,
                "feedback": None,
            }
        )
        working_state["qa_history"] = qa_history

        # 获取 LLM 客户端
        chat_client = await self._llm_registry.get_chat_client()
        old_difficulty = working_state.get("difficulty", "mid")

        # 运行 Agent（评估答案 + 决定下一步）
        working_state = await self._graph.run_next_turn(
            chat_client=chat_client,
            invoker=self._invoker,
            reference_loader=self._reference_loader,
            state=working_state,
            user_answer=answer,
        )

        # graph 成功后写回
        self._put_state(session_id, working_state)
        new_difficulty: str = working_state.get("difficulty", "mid")

        # 提取最新评估结果
        latest_qa: list[QARecord] = working_state.get("qa_history", [])
        last_score: int | None = latest_qa[-1]["score"] if latest_qa else None
        last_feedback: str | None = latest_qa[-1]["feedback"] if latest_qa else None

        # 构造下一题 DTO
        next_question = None
        next_q_text = working_state.get("current_question")
        if not working_state.get("finished") and next_q_text:
            next_question = AdaptiveQuestionDTO(
                question=next_q_text,
                category=working_state.get("current_category") or "通用",
                difficulty=new_difficulty,
                question_index=working_state.get("turn_count", 0),
            )

        return AdaptiveAnswerResultDTO(
            score=last_score,
            feedback=last_feedback,
            next_question=next_question,
            finished=bool(working_state.get("finished", False)),
            difficulty_changed=new_difficulty != old_difficulty,
            new_difficulty=new_difficulty if new_difficulty != old_difficulty else None,
        )

    async def get_report(self, session_id: str) -> AdaptiveReportDTO:
        """获取面试最终报告。"""
        state = self._get_state(session_id)
        report = state.get("final_report")
        if report is None:
            # 面试未结束时也可以获取中间报告
            qa_history: list[QARecord] = state.get("qa_history", [])
            category_scores = state.get("category_scores", {})
            all_scores = [q["score"] for q in qa_history if q.get("score") is not None]
            overall_score = int(sum(s for s in all_scores if s is not None) / len(all_scores)) if all_scores else 0
            report = {
                "session_id": session_id,
                "total_questions": len(qa_history),
                "overall_score": overall_score,
                "category_scores": {k: int(sum(v) / len(v)) for k, v in category_scores.items() if v},
                "questions": qa_history,
                "difficulty_progression": state.get("difficulty", "mid"),
            }

        return AdaptiveReportDTO(**report)

    def _get_state(self, session_id: str) -> AdaptiveInterviewState:
        """获取会话状态，不存在则抛异常。访问时刷新 LRU 位置。"""
        state = self._sessions.get(session_id)
        if state is None:
            raise BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND, f"Agent 面试会话不存在: {session_id}")
        self._sessions.move_to_end(session_id)
        return state

    def _put_state(self, session_id: str, state: AdaptiveInterviewState) -> None:
        """写入会话状态，超出容量时淘汰最久未访问的。"""
        self._sessions[session_id] = state
        self._sessions.move_to_end(session_id)
        while len(self._sessions) > _MAX_SESSIONS:
            evicted_id, _ = self._sessions.popitem(last=False)
            logger.info("淘汰 Agent 会话: %s", evicted_id)

    def _to_session_dto(self, state: AdaptiveInterviewState) -> AdaptiveSessionDTO:
        """将内部状态转换为 DTO。"""
        current_question = None
        current_q_text = state.get("current_question")
        if current_q_text and not state.get("finished"):
            current_question = AdaptiveQuestionDTO(
                question=current_q_text,
                category=state.get("current_category") or "通用",
                difficulty=state.get("difficulty", "mid"),
                question_index=state.get("turn_count", 0),
            )

        category_scores = state.get("category_scores", {})
        avg_scores = {k: sum(v) / len(v) for k, v in category_scores.items() if v}

        return AdaptiveSessionDTO(
            session_id=state.get("session_id", ""),
            skill_id=state.get("skill_id", "java-backend"),
            difficulty=state.get("difficulty", "mid"),
            turn_count=state.get("turn_count", 0),
            max_turns=state.get("max_turns", 6),
            current_question=current_question,
            finished=state.get("finished", False),
            category_scores=avg_scores,
            decision_trace=state.get("decision_trace"),
        )
