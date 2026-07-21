"""语音面试对话 LLM 流式回复测试。"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

from app.application.voice.dialogue_llm import DialogueContext, VoiceDialogueLlm


class _FakeChunk:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLlm:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    def astream(self, _messages: object) -> AsyncIterator[_FakeChunk]:
        async def _gen() -> AsyncIterator[_FakeChunk]:
            for token in self._tokens:
                yield _FakeChunk(token)

        return _gen()


def _context() -> DialogueContext:
    return DialogueContext(
        role_type="Java面试官",
        skill_id="java-backend",
        difficulty="mid",
        current_phase="TECH",
        custom_jd_text=None,
        llm_provider_id=None,
    )


def _make_llm(tokens: list[str]) -> tuple[VoiceDialogueLlm, MagicMock]:
    registry = MagicMock()
    registry.get_voice_chat_client = AsyncMock(return_value=_FakeLlm(tokens))
    sanitizer = MagicMock()
    sanitizer.sanitize = MagicMock(side_effect=lambda s: s)
    return VoiceDialogueLlm(registry, sanitizer), registry


class TestStreamReply:
    async def test_yields_non_empty_tokens(self) -> None:
        llm, registry = _make_llm(["你好", "", "，请", "介绍"])
        tokens = [t async for t in llm.stream_reply(_context(), history="", answer="我叫张三")]
        assert tokens == ["你好", "，请", "介绍"]
        registry.get_voice_chat_client.assert_awaited_once_with(None)

    async def test_uses_provider_id_when_present(self) -> None:
        ctx = DialogueContext(
            role_type="r",
            skill_id="s",
            difficulty="mid",
            current_phase="TECH",
            custom_jd_text="要求 Java",
            llm_provider_id=7,
        )
        llm, registry = _make_llm(["ok"])
        _ = [t async for t in llm.stream_reply(ctx, history="Q1\nA1", answer="回答")]
        registry.get_voice_chat_client.assert_awaited_once_with(7)
