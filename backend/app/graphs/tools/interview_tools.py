# ruff: noqa: N815  LLM 输出模型字段须 camelCase 对齐 prompt Output Format
"""自适应面试 Agent 工具：generate_question / evaluate_answer / lookup_reference / adjust_strategy。

工具遵循 LangChain @tool 规范，由 adaptive_interview.py 的 ReAct Agent 节点调用。
generate_question 和 evaluate_answer 通过 StructuredOutputInvoker 调用 LLM；
lookup_reference 为本地文件读取（<10ms）；adjust_strategy 为纯函数。
"""

import logging
from dataclasses import dataclass

from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.domain.errors import ErrorCode
from app.domain.services.adaptive_strategy import StrategyUpdate
from app.infrastructure.ai.prompt_loader import load_prompt
from app.infrastructure.ai.structured_output import StructuredOutputInvoker
from app.infrastructure.skills.reference_loader import ReferenceLoader

logger = logging.getLogger(__name__)


# ==================== 输出模型 ====================


class GeneratedQuestion(BaseModel):
    """LLM 生成的单道面试题。"""

    question: str
    type: str = "DIRECTION"
    category: str = ""
    followUp: str = ""


class AnswerEvaluation(BaseModel):
    """LLM 对候选人回答的即时评估。"""

    score: int = Field(ge=0, le=10, description="0-10 分")
    feedback: str = ""
    shouldFollowUp: bool = False
    followUpSuggestion: str = ""


# ==================== 工具上下文（运行时注入） ====================


@dataclass
class InterviewToolContext:
    """运行时注入的工具依赖（通过 RunnableConfig.configurable 传递）。"""

    chat_client: ChatOpenAI
    invoker: StructuredOutputInvoker
    reference_loader: ReferenceLoader
    skill_id: str
    resume_text: str


# ==================== 工具实现 ====================

_GENERATE_SYSTEM_PROMPT = "adaptive-agent-generate-question-system"
_GENERATE_USER_PROMPT = "adaptive-agent-generate-question-user"
_EVALUATE_SYSTEM_PROMPT = "adaptive-agent-evaluate-answer-system"
_EVALUATE_USER_PROMPT = "adaptive-agent-evaluate-answer-user"


async def generate_question_impl(
    category: str,
    difficulty: str,
    context: str,
    tool_ctx: InterviewToolContext,
) -> GeneratedQuestion:
    """按指定方向和难度生成一道面试题。"""
    system_tpl = await load_prompt(_GENERATE_SYSTEM_PROMPT)
    user_tpl = await load_prompt(_GENERATE_USER_PROMPT)
    system_prompt = system_tpl.format()
    user_prompt = user_tpl.format(
        category=category,
        difficulty=difficulty,
        context=context,
        resumeText=tool_ctx.resume_text[:2000] if tool_ctx.resume_text else "无",
    )
    return await tool_ctx.invoker.invoke(
        llm=tool_ctx.chat_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        output_model=GeneratedQuestion,
        error_code=ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED,
        error_prefix="Agent 出题失败：",
        log_context="Agent 出题",
    )


async def evaluate_answer_impl(
    question: str,
    answer: str,
    category: str,
    tool_ctx: InterviewToolContext,
) -> AnswerEvaluation:
    """即时评估候选人对某题的回答。"""
    system_tpl = await load_prompt(_EVALUATE_SYSTEM_PROMPT)
    user_tpl = await load_prompt(_EVALUATE_USER_PROMPT)
    system_prompt = system_tpl.format()
    user_prompt = user_tpl.format(
        question=question,
        answer=answer,
        category=category,
    )
    return await tool_ctx.invoker.invoke(
        llm=tool_ctx.chat_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        output_model=AnswerEvaluation,
        error_code=ErrorCode.INTERVIEW_EVALUATION_FAILED,
        error_prefix="Agent 即时评估失败：",
        log_context="Agent 即时评估",
    )


async def lookup_reference_impl(
    skill_id: str,
    category: str,
    tool_ctx: InterviewToolContext,
) -> str:
    """检索技能参考资料（本地文件读取，<10ms）。"""
    from app.graphs.tools.skill_tool import _load_skill_reference

    try:
        content = _load_skill_reference(skill_id, category)
        if content:
            return content[:3000] if len(content) > 3000 else content
        return f"未找到 {skill_id}/{category} 的参考资料"
    except Exception as e:
        logger.warning("Agent lookup_reference 失败: skill=%s, category=%s, error=%s", skill_id, category, e)
        return f"参考资料加载失败: {e}"


def adjust_strategy_impl(
    category_scores: dict[str, list[int]],
    current_difficulty: str,
    turn_count: int,
    max_turns: int,
) -> StrategyUpdate:
    """根据候选人各维度得分，计算策略调整建议（纯函数，无 LLM）。"""
    from app.domain.services.adaptive_strategy import compute_strategy_update

    return compute_strategy_update(category_scores, current_difficulty, turn_count, max_turns)


# ==================== 工具参数 Schemas（供 StructuredTool.from_schema） ====================


class GenerateQuestionArgs(BaseModel):
    """按指定方向和难度生成一道面试题。"""

    category: str = Field(description="面试方向（如 JAVA, MYSQL, REDIS, SPRING, PROJECT）")
    difficulty: str = Field(description="难度级别（junior/mid/senior）")
    context: str = Field(default="", description="额外上下文（如候选人上一题的表现摘要）")


class EvaluateAnswerArgs(BaseModel):
    """即时评估候选人对某题的回答。"""

    question: str = Field(description="面试问题文本")
    answer: str = Field(description="候选人的回答")
    category: str = Field(default="通用", description="问题所属方向")


class LookupReferenceArgs(BaseModel):
    """检索面试技能参考资料。"""

    skill_id: str = Field(description="技能标识（如 java-backend, python-backend）")
    category: str = Field(description="方向标识（如 JAVA, MYSQL, REDIS）")


class AdjustStrategyArgs(BaseModel):
    """根据候选人当前各维度表现，计算下一步出题策略调整建议。"""

    scores_summary: str = Field(description="当前各维度得分摘要（JSON 格式）")


# ==================== StructuredTool 定义（供 Agent bind_tools） ====================
# 不传 func → 直接调用会报错，防止误调时静默返回占位字符串

generate_question_tool = StructuredTool.from_schema(
    name="generate_question",
    description="按指定方向和难度生成一道面试题。",
    args_schema=GenerateQuestionArgs,
)

evaluate_answer_tool = StructuredTool.from_schema(
    name="evaluate_answer",
    description="即时评估候选人对某题的回答。",
    args_schema=EvaluateAnswerArgs,
)

lookup_reference_tool = StructuredTool.from_schema(
    name="lookup_reference",
    description="检索面试技能参考资料。当需要了解某个技术方向的深入知识以出更好的追问时调用。",
    args_schema=LookupReferenceArgs,
)

adjust_strategy_tool = StructuredTool.from_schema(
    name="adjust_strategy",
    description="根据候选人当前各维度表现，计算下一步出题策略调整建议。",
    args_schema=AdjustStrategyArgs,
)

# 导出工具列表，供 Agent 绑定
INTERVIEW_AGENT_TOOLS = [generate_question_tool, evaluate_answer_tool, lookup_reference_tool, adjust_strategy_tool]
