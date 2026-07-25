"""AgentDialogueLlm 单元测试：验证 tool-calling 流式对话。"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.voice.agent_dialogue_llm import AgentDialogueLlm
from app.application.voice.dialogue_llm import DialogueContext


class _FakeChunk:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeAIMessage:
    """模拟 AIMessage（无 tool_call）。"""

    def __init__(self, content: str, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


def _context() -> DialogueContext:
    return DialogueContext(
        role_type="Java面试官",
        skill_id="java-backend",
        difficulty="mid",
        current_phase="TECH",
        custom_jd_text=None,
        llm_provider=None,
    )


def _make_agent_llm(
    ainvoke_response: _FakeAIMessage,
    stream_tokens: list[str] | None = None,
) -> tuple[AgentDialogueLlm, MagicMock]:
    registry = MagicMock()

    # bind_tools 返回一个有 ainvoke 的 mock
    llm_with_tools = AsyncMock()
    llm_with_tools.ainvoke = AsyncMock(return_value=ainvoke_response)

    # 原始 llm 的 astream
    llm_mock = MagicMock()
    llm_mock.bind_tools = MagicMock(return_value=llm_with_tools)

    if stream_tokens:

        async def _gen(*args: object, **kwargs: object) -> AsyncIterator[_FakeChunk]:
            for t in stream_tokens:
                yield _FakeChunk(t)

        llm_mock.astream = _gen
    else:
        llm_mock.astream = AsyncMock(return_value=iter([]))

    registry.get_voice_chat_client = AsyncMock(return_value=llm_mock)
    registry.resolve_provider_id_by_name = AsyncMock(return_value=None)

    sanitizer = MagicMock()
    sanitizer.sanitize = MagicMock(side_effect=lambda s: s)

    return AgentDialogueLlm(registry, sanitizer), registry


class TestAgentDialogueLlmNoToolCall:
    """没有 tool-call 时，使用 astream 流式返回。"""

    @pytest.mark.asyncio
    async def test_yields_text_without_tool_call(self) -> None:
        response = _FakeAIMessage(content="这是一个好问题，请详细说明...", tool_calls=[])
        agent_llm, _registry = _make_agent_llm(response, stream_tokens=["这是", "一个", "好问题"])
        tokens = [t async for t in agent_llm.stream_reply(_context(), history="", answer="我的回答")]
        # 现在无 tool-call 时也走 astream，应产出增量 token
        assert "这是" in "".join(tokens)


class TestAgentDialogueLlmWithToolCall:
    """LLM 调用工具后再次流式生成。"""

    @pytest.mark.asyncio
    async def test_executes_tool_and_streams(self) -> None:
        tool_call = {
            "id": "call_123",
            "name": "lookup_skill_knowledge",
            "args": {"skill_id": "java-backend", "category": "JAVA"},
        }
        response = _FakeAIMessage(content="", tool_calls=[tool_call])
        agent_llm, _registry = _make_agent_llm(response, stream_tokens=["追问", "：", "说说GC"])

        with patch("app.application.voice.agent_dialogue_llm.lookup_skill_knowledge") as mock_tool:
            mock_tool.invoke = MagicMock(return_value="Java GC 知识参考...")
            tokens = [t async for t in agent_llm.stream_reply(_context(), history="", answer="我了解 JVM")]

        assert "追问" in "".join(tokens)


class TestSkillToolLoading:
    """Skill Tool 本地文件加载。"""

    def test_loads_existing_reference(self) -> None:
        from app.graphs.tools.skill_tool import _load_skill_reference

        # java-backend 技能应该有 SKILL.md
        result = _load_skill_reference("java-backend", "nonexistent-category")
        # 应该 fallback 到 SKILL.md
        assert "java-backend" in result.lower() or "Java" in result or "面试" in result

    def test_returns_not_found_for_unknown_skill_and_category(self) -> None:
        from app.graphs.tools.skill_tool import _load_skill_reference

        result = _load_skill_reference("nonexistent-skill-xyz", "TOTALLY_UNKNOWN_CATEGORY_XYZ")
        assert "未找到" in result
