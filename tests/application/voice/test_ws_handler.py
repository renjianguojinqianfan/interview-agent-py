"""语音面试 WebSocket 编排器测试：握手 + ASR 桥接 + LLM 回合 + 句子级 TTS + 回声抑制。

各泵/回合单独测试以避免并发竞态；LLM/TTS/时钟均以 fake 注入。
"""

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

from fastapi import WebSocketDisconnect

from app.application.voice.ws_handler import (
    WS_CLOSE_INVALID_STATE,
    WS_CLOSE_SESSION_NOT_FOUND,
    VoiceWsOrchestrator,
)
from app.infrastructure.redis.voice_session_cache import CachedVoiceSession
from app.infrastructure.voice.asr import AsrTranscript
from app.infrastructure.voice.tts import TtsConnectionClosed, TtsEvent


class _FakeClientWs:
    def __init__(self, incoming: list[str] | None = None) -> None:
        self._incoming = list(incoming or [])
        self.accepted = False
        self.sent: list[dict] = []
        self.closed_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if not self._incoming:
            raise WebSocketDisconnect(code=1000)
        return self._incoming.pop(0)

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    def sent_of(self, msg_type: str) -> list[dict]:
        return [m for m in self.sent if m.get("type") == msg_type]


class _FakeAsr:
    def __init__(self, events: list[object] | None = None) -> None:
        self._events = list(events or [])
        self.connected = False
        self.closed = False
        self.audio: list[str] = []

    async def connect(self) -> None:
        self.connected = True

    async def send_audio(self, base64_pcm: str) -> None:
        self.audio.append(base64_pcm)

    async def finish(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True

    async def receive(self) -> AsrTranscript | None:
        if not self._events:
            from app.infrastructure.voice.asr import AsrConnectionClosed

            raise AsrConnectionClosed("closed", "connection closed")
        event = self._events.pop(0)
        if isinstance(event, Exception):
            raise event
        assert event is None or isinstance(event, AsrTranscript)
        return event


class _FakeTts:
    def __init__(self, events: list[TtsEvent]) -> None:
        self._events = list(events)
        self.synth: list[str] = []
        self.closed = False

    async def connect(self) -> None:
        pass

    async def synthesize(self, text: str) -> None:
        self.synth.append(text)

    async def finish(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True

    async def receive(self) -> TtsEvent | None:
        if not self._events:
            raise TtsConnectionClosed("closed", "closed")
        return self._events.pop(0)


class _FakeDialogueLlm:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.calls: list[tuple[str, str]] = []

    def stream_reply(self, _context: object, history: str, answer: str) -> AsyncIterator[str]:
        self.calls.append((history, answer))

        async def _gen() -> AsyncIterator[str]:
            for token in self._tokens:
                yield token

        return _gen()


def _cached(status: str) -> CachedVoiceSession:
    return CachedVoiceSession(
        session_id="1",
        user_id="default",
        role_type="Java面试官",
        skill_id="java-backend",
        difficulty="mid",
        current_phase="TECH",
        status=status,
        resume_id=None,
        llm_provider=None,
    )


def _orm(status: str = "IN_PROGRESS") -> MagicMock:
    return MagicMock(
        status=status,
        role_type="Java面试官",
        skill_id="java-backend",
        difficulty="mid",
        current_phase="TECH",
        custom_jd_text=None,
        llm_provider=None,
    )


def _make_session_factory() -> MagicMock:
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


def _make_orchestrator(
    cached_status: str | None = None,
    db_orm: MagicMock | None = None,
    asr: _FakeAsr | None = None,
    tokens: list[str] | None = None,
    tts_events: list[TtsEvent] | None = None,
    debounce_ms: float = 2500,
    now_ms: float = 0.0,
) -> VoiceWsOrchestrator:
    cache = MagicMock()
    cache.get_session = AsyncMock(return_value=_cached(cached_status) if cached_status else None)
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=db_orm)
    asr_loader = MagicMock()
    asr_loader.load = AsyncMock(return_value=MagicMock())
    tts_loader = MagicMock()
    tts_loader.load = AsyncMock(return_value=MagicMock())
    events = tts_events if tts_events is not None else [TtsEvent("QUJD", done=False), TtsEvent(None, done=True)]
    return VoiceWsOrchestrator(
        session_id=1,
        cache=cache,
        repository=repository,
        session_factory=_make_session_factory(),
        asr_config_loader=asr_loader,
        asr_client_factory=lambda _config: asr or _FakeAsr(),
        tts_config_loader=tts_loader,
        tts_client_factory=lambda _config: _FakeTts(list(events)),
        dialogue_llm=_FakeDialogueLlm(tokens or []),  # type: ignore[arg-type]
        now_ms=lambda: now_ms,
        debounce_ms=debounce_ms,
    )


def _ready(orch: VoiceWsOrchestrator) -> None:
    """为直接调用 _commit_turn/_synthesize 的测试预置上下文与 TTS 配置。"""
    from app.application.voice.dialogue_llm import DialogueContext

    orch._context = DialogueContext(
        role_type="r", skill_id="s", difficulty="mid", current_phase="TECH", custom_jd_text=None, llm_provider_id=None
    )
    orch._tts_config = MagicMock()


class TestHandshake:
    async def test_closes_when_session_not_found(self) -> None:
        orch = _make_orchestrator(cached_status=None, db_orm=None)
        ws = _FakeClientWs()
        await orch.run(ws)
        assert ws.closed_code == WS_CLOSE_SESSION_NOT_FOUND
        assert ws.accepted is False

    async def test_closes_when_status_not_in_progress(self) -> None:
        orch = _make_orchestrator(cached_status="PAUSED")
        ws = _FakeClientWs()
        await orch.run(ws)
        assert ws.closed_code == WS_CLOSE_INVALID_STATE

    async def test_accepts_and_connects_when_in_progress(self) -> None:
        asr = _FakeAsr()
        orch = _make_orchestrator(cached_status="IN_PROGRESS", db_orm=_orm(), asr=asr)
        ws = _FakeClientWs()
        await orch.run(ws)
        assert ws.accepted is True
        assert asr.connected is True
        assert asr.closed is True


class TestAsrToClient:
    async def test_partial_pushed_as_subtitle(self) -> None:
        orch = _make_orchestrator()
        _ready(orch)
        ws = _FakeClientWs()
        asr = _FakeAsr(events=[AsrTranscript(text="今天", is_final=False)])
        await orch._asr_to_client(ws, asr)
        assert ws.sent_of("subtitle") == [{"type": "subtitle", "text": "今天", "isFinal": False}]

    async def test_final_long_answer_commits_immediately(self) -> None:
        orch = _make_orchestrator(tokens=["你好。"])
        _ready(orch)
        ws = _FakeClientWs()
        await orch._on_final_transcript(ws, "a" * 25)
        assert orch.history == [("a" * 25, "你好。")]
        assert len(ws.sent_of("text")) >= 1

    async def test_final_short_answer_debounce_commits(self) -> None:
        orch = _make_orchestrator(tokens=["嗯，继续。"], debounce_ms=0)
        _ready(orch)
        ws = _FakeClientWs()
        await orch._on_final_transcript(ws, "短")
        assert orch._commit_task is not None
        await orch._commit_task
        assert orch.history == [("短", "嗯，继续。")]


class TestCommitTurn:
    async def test_streams_text_and_audio_and_updates_history(self) -> None:
        orch = _make_orchestrator(tokens=["你好", "。", "请介绍"])
        _ready(orch)
        orch._final_segments = ["我叫张三"]
        ws = _FakeClientWs()
        await orch._commit_turn(ws)

        text_msgs = ws.sent_of("text")
        assert [m for m in text_msgs if not m["isFinal"]]  # 逐 token
        finals = [m for m in text_msgs if m["isFinal"]]
        assert finals and finals[-1]["text"] == "你好。请介绍"

        audio_msgs = ws.sent_of("audio_chunk")
        assert any(m["data"] == "QUJD" for m in audio_msgs)
        assert audio_msgs[-1]["isLast"] is True
        assert orch.history == [("我叫张三", "你好。请介绍")]

    async def test_empty_answer_noop(self) -> None:
        orch = _make_orchestrator(tokens=["x"])
        _ready(orch)
        orch._final_segments = []
        ws = _FakeClientWs()
        await orch._commit_turn(ws)
        assert ws.sent == []
        assert orch.history == []


class TestEchoSuppression:
    async def test_drops_audio_while_ai_speaking(self) -> None:
        orch = _make_orchestrator()
        orch._ai_speaking = True
        ws = _FakeClientWs(incoming=[json.dumps({"type": "audio", "data": "QUJD"})])
        asr = _FakeAsr()
        await orch._client_to_asr(ws, asr)
        assert asr.audio == []

    async def test_drops_audio_within_cooldown(self) -> None:
        orch = _make_orchestrator(now_ms=100.0)
        orch._mute_until_ms = 500.0
        ws = _FakeClientWs(incoming=[json.dumps({"type": "audio", "data": "QUJD"})])
        asr = _FakeAsr()
        await orch._client_to_asr(ws, asr)
        assert asr.audio == []

    async def test_forwards_audio_when_not_muted(self) -> None:
        orch = _make_orchestrator(now_ms=1000.0)
        ws = _FakeClientWs(incoming=[json.dumps({"type": "audio", "data": "QUJD"})])
        asr = _FakeAsr()
        await orch._client_to_asr(ws, asr)
        assert asr.audio == ["QUJD"]

    async def test_control_finish_ends(self) -> None:
        orch = _make_orchestrator()
        ws = _FakeClientWs(incoming=[json.dumps({"type": "control", "action": "finish"})])
        asr = _FakeAsr()
        await orch._client_to_asr(ws, asr)
        # finish 后循环结束，无异常即通过
        assert asr.audio == []

    async def test_bad_message_sends_error(self) -> None:
        orch = _make_orchestrator()
        ws = _FakeClientWs(incoming=["not-json"])
        asr = _FakeAsr()
        await orch._client_to_asr(ws, asr)
        assert ws.sent_of("error")[0]["code"] == "bad_message"
