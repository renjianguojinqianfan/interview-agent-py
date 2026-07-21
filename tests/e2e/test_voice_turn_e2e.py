"""语音面试一回合真实 Postgres 端到端（#20 AC1：真库回合持久化）。

复用 VoiceWsOrchestrator（真 VoiceInterviewRepository + live PG + 假 ASR/TTS/LLM），
驱动一次 _commit_turn，断言对话消息真实写入 Postgres —— 补足 test_ws_handler
（mock DB 编排）缺失的"回合持久化全链落真库"覆盖。ASR/TTS/LLM 外部服务不可真调，故假化。
"""

import json
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.voice.dialogue_llm import DialogueContext
from app.application.voice.ws_handler import VoiceWsOrchestrator
from app.infrastructure.db.models.voice_interview import VoiceInterviewMessage, VoiceInterviewSession
from app.infrastructure.db.repositories.voice_interview_repository import VoiceInterviewRepository
from app.infrastructure.voice.tts import TtsEvent


class _FakeWs:
    """收集编排器下发的消息（无需真实 WebSocket）。"""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None: ...

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000) -> None: ...


class _FakeTts:
    def __init__(self) -> None:
        self._events = [TtsEvent("QUJD", done=False), TtsEvent(None, done=True)]

    async def connect(self) -> None: ...

    async def synthesize(self, text: str) -> None: ...

    async def finish(self) -> None: ...

    async def close(self) -> None: ...

    async def receive(self) -> TtsEvent | None:
        return self._events.pop(0) if self._events else None


class _FakeDialogueLlm:
    def stream_reply(self, _context: object, _history: str, _answer: str) -> AsyncIterator[str]:
        async def _gen() -> AsyncIterator[str]:
            for token in ["你好", "，", "请介绍你的项目。"]:
                yield token

        return _gen()


async def _seed_voice_session(factory: async_sessionmaker) -> int:
    async with factory() as db:
        sess = VoiceInterviewSession(role_type="Java面试官", status="IN_PROGRESS", current_phase="TECH")
        db.add(sess)
        await db.flush()
        session_id = sess.id
        await db.commit()
    return session_id


async def test_voice_turn_persists_to_real_db_e2e(live_session_factory: async_sessionmaker) -> None:
    """一回合：假 ASR 答案 -> 假 LLM 流式回复 -> 假 TTS -> 真库落对话消息。"""
    session_id = await _seed_voice_session(live_session_factory)

    orch = VoiceWsOrchestrator(
        session_id=session_id,
        cache=MagicMock(),
        repository=VoiceInterviewRepository(),
        session_factory=live_session_factory,
        asr_config_loader=MagicMock(),
        asr_client_factory=lambda _config: MagicMock(),
        tts_config_loader=MagicMock(),
        tts_client_factory=lambda _config: _FakeTts(),
        dialogue_llm=_FakeDialogueLlm(),  # type: ignore[arg-type]
        opening_loader=MagicMock(),
    )
    orch._context = DialogueContext(
        role_type="Java面试官",
        skill_id="java-backend",
        difficulty="mid",
        current_phase="TECH",
        custom_jd_text=None,
        llm_provider_id=None,
    )
    orch._tts_config = MagicMock()
    orch._final_segments = ["我做过一个高并发系统"]

    await orch._commit_turn(_FakeWs())

    async with live_session_factory() as db:
        rows = (
            (await db.execute(select(VoiceInterviewMessage).where(VoiceInterviewMessage.session_id == session_id)))
            .scalars()
            .all()
        )

    assert rows, "回合未持久化到真库"
    assert any(r.ai_generated_text and "请介绍" in r.ai_generated_text for r in rows)
