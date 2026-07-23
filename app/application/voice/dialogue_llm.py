"""语音面试对话 LLM：构造面试官 prompt 并流式生成回复。

复用 llm_registry 的语音流式客户端（get_voice_chat_client）与 rag 的 astream 增量模式。
接收会话上下文 + 已格式化对话历史 + 候选人最新回答，流式产出面试官下一句的增量 token。
异步编排（句子级并发 TTS、回声抑制）在 ws_handler.py。
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.domain.services.voice_dialogue import MAX_AI_REPLY_CHARS
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.prompt_loader import load_prompt
from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = "voice-interview-dialogue-system"
_USER_PROMPT = "voice-interview-dialogue-user"
_EMPTY_HISTORY = "（暂无）"


@dataclass(frozen=True)
class DialogueContext:
    """面试官对话的会话上下文（构造 prompt 用）。"""

    role_type: str
    skill_id: str
    difficulty: str
    current_phase: str
    custom_jd_text: str | None
    llm_provider: str | None


def _content_to_str(content: Any) -> str:
    """从 langchain 流式 chunk.content 提取文本（兼容 str 与 list 分块）。"""
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


class VoiceDialogueLlm:
    """语音面试官对话的 LLM 流式回复生成。"""

    def __init__(self, llm_registry: LlmProviderRegistry, sanitizer: PromptSanitizer | None = None) -> None:
        self._llm_registry = llm_registry
        self._sanitizer = sanitizer or PromptSanitizer()

    async def stream_reply(self, context: DialogueContext, history: str, answer: str) -> AsyncIterator[str]:
        """流式生成面试官下一句回复的增量 token。"""
        messages = await self._build_messages(context, history, answer)
        provider_id = await self._llm_registry.resolve_provider_id_by_name(context.llm_provider)
        llm = await self._llm_registry.get_voice_chat_client(provider_id)
        async for chunk in llm.astream(messages):
            token = _content_to_str(chunk.content)
            if token:
                yield token

    async def _build_messages(self, context: DialogueContext, history: str, answer: str) -> list[BaseMessage]:
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
        user = user_tpl.format(
            history=(self._sanitizer.sanitize(history) or _EMPTY_HISTORY) if history.strip() else _EMPTY_HISTORY,
            answer=self._sanitizer.sanitize(answer) or "",
        )
        return [SystemMessage(content=system), HumanMessage(content=user)]
