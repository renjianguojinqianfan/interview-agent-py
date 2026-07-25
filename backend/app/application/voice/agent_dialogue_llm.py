"""带 Tool-Calling 的语音面试官对话 LLM：对标 Java 版 SkillsTool + ToolCallingAdvisor。

与 VoiceDialogueLlm 接口一致（stream_reply），但内部支持单次 tool-call：
LLM 可自主决定是否调用 lookup_skill_knowledge 检索技能参考资料，然后基于
检索到的知识继续生成回复。

通过 DI 替换注入（deps.py VOICE_AGENT_ENABLED 控制），ws_handler.py 零修改。
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.tool import ToolCall

from app.application.voice.dialogue_llm import DialogueContext
from app.domain.services.voice_dialogue import MAX_AI_REPLY_CHARS
from app.graphs.tools.skill_tool import SKILL_TOOLS, lookup_skill_knowledge
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.prompt_loader import load_prompt
from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = "voice-interview-dialogue-system"
_USER_PROMPT = "voice-interview-dialogue-user"
_EMPTY_HISTORY = "（暂无）"


def _content_to_str(content: Any) -> str:
    """从 langchain 流式 chunk.content 提取文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return ""


class AgentDialogueLlm:
    """带 tool-calling 的语音面试官对话，与 VoiceDialogueLlm 接口一致。

    核心区别：
    - LLM 绑定 lookup_skill_knowledge 工具
    - 第一次调用可能返回 tool_call -> 执行工具 -> 追加结果 -> 第二次流式调用
    - 最多 1 次 tool-call（不循环），额外延迟 ~1-2s，可接受

    接口契约与 VoiceDialogueLlm.stream_reply 完全一致，ws_handler 无需感知差异。
    """

    def __init__(self, llm_registry: LlmProviderRegistry, sanitizer: PromptSanitizer | None = None) -> None:
        self._llm_registry = llm_registry
        self._sanitizer = sanitizer or PromptSanitizer()

    async def stream_reply(self, context: DialogueContext, history: str, answer: str) -> AsyncIterator[str]:
        """流式生成面试官下一句回复（支持 tool-calling 增强）。"""
        messages = await self._build_messages(context, history, answer)
        provider_id = await self._llm_registry.resolve_provider_id_by_name(context.llm_provider)
        llm = await self._llm_registry.get_voice_chat_client(provider_id)

        # 绑定工具并做第一次调用（非流式，需要判断是否有 tool_call）
        llm_with_tools = llm.bind_tools(SKILL_TOOLS)
        try:
            response: AIMessage = await llm_with_tools.ainvoke(messages)
        except Exception as e:
            # tool-binding 调用失败 -> 回退到纯流式（无工具）
            logger.warning("Agent dialogue tool-call 失败，回退纯流式: %s", e)
            async for token in self._fallback_stream(llm, messages):
                yield token
            return

        # 检查是否有 tool calls
        if response.tool_calls:
            # 执行工具（本地文件读取，<10ms）
            tool_call = response.tool_calls[0]
            tool_result = self._execute_skill_tool(tool_call, context)

            # 追加 tool 结果到消息链
            messages.append(response)
            messages.append(ToolMessage(content=tool_result, tool_call_id=tool_call.get("id", "")))

            logger.info(
                "Agent dialogue tool-call 完成: skill=%s, category=%s",
                tool_call["args"].get("skill_id", ""),
                tool_call["args"].get("category", ""),
            )

            # 第二次调用（流式，基于工具结果生成回复）
            async for chunk in llm.astream(messages):
                token = _content_to_str(chunk.content)
                if token:
                    yield token
        else:
            # LLM 决定不调用工具 -> 仍需流式返回以保持增量契约
            async for chunk in llm.astream(messages):
                token = _content_to_str(chunk.content)
                if token:
                    yield token

    def _execute_skill_tool(self, tool_call: ToolCall, context: DialogueContext) -> str:
        """执行 skill 工具（同步，本地文件读取）。"""
        args = tool_call.get("args", {})
        skill_id = args.get("skill_id", context.skill_id)
        category = args.get("category", "")
        try:
            result = lookup_skill_knowledge.invoke({"skill_id": skill_id, "category": category, "query": ""})
            return str(result)
        except Exception as e:
            logger.warning("Skill tool 执行失败: %s", e)
            return f"参考资料加载失败: {e}"

    async def _fallback_stream(self, llm: Any, messages: list[BaseMessage]) -> AsyncIterator[str]:
        """工具调用失败时的纯流式回退。"""
        async for chunk in llm.astream(messages):
            token = _content_to_str(chunk.content)
            if token:
                yield token

    async def _build_messages(self, context: DialogueContext, history: str, answer: str) -> list[BaseMessage]:
        """构造消息（复用 VoiceDialogueLlm 相同的 prompt 模板）。"""
        system_tpl = await load_prompt(_SYSTEM_PROMPT)
        user_tpl = await load_prompt(_USER_PROMPT)
        jd = (context.custom_jd_text or "").strip()
        jd_section = f"- 岗位要求：{self._sanitizer.sanitize(jd)}" if jd else ""
        system = system_tpl.format(
            roleType=context.role_type,
            skillId=context.skill_id,
            difficulty=context.difficulty,
            currentPhase=context.current_phase,
            maxReplyChars=MAX_AI_REPLY_CHARS,
            jdSection=jd_section,
        )
        # 追加工具使用提示
        system += (
            "\n\n你可以调用 lookup_skill_knowledge 工具查阅技能参考资料，"
            "以出更精准的追问。仅在你需要确认某个技术细节时调用，不要每次都调用。"
        )
        user = user_tpl.format(
            history=(self._sanitizer.sanitize(history) or _EMPTY_HISTORY) if history.strip() else _EMPTY_HISTORY,
            answer=self._sanitizer.sanitize(answer) or "",
        )
        return [SystemMessage(content=system), HumanMessage(content=user)]
