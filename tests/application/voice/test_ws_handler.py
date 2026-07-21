"""语音面试 WebSocket 编排器测试：握手 + ASR 桥接 + LLM 回合 + 句子级 TTS + 回声抑制。

各泵/回合单独测试以避免并发竞态；LLM/TTS/时钟均以 fake 注入。
"""

import asyncio
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
from app.infrastructure.voice.asr import AsrConnectionClosed, AsrTranscript
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
    opening: str = "",
    asr_max_reconnect: int = 0,
    asr_reconnect_delay: float = 0.0,
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
    opening_loader = MagicMock()
    opening_loader.get_opening_question = AsyncMock(return_value=opening)
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
        opening_loader=opening_loader,
        now_ms=lambda: now_ms,
        debounce_ms=debounce_ms,
        asr_max_reconnect=asr_max_reconnect,
        asr_reconnect_delay_seconds=asr_reconnect_delay,
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


class _FakeVoiceRepo:
    """支持 #17 持久化方法的假仓储。"""

    def __init__(self, latest: object = None, count: int = 0, orm: object = None) -> None:
        self._latest = latest
        self._count = count
        self._orm = orm
        self.saved: list[object] = []

    async def find_latest_unanswered_message(self, _session: object, _pk: int) -> object:
        return self._latest

    async def count_messages_by_session(self, _session: object, _pk: int) -> int:
        return self._count

    async def save_message(self, _session: object, message: object) -> object:
        self.saved.append(message)
        return message

    async def get_by_id(self, _session: object, _pk: int) -> object:
        return self._orm

    async def update_current_phase(self, _session: object, orm: object, phase: str) -> None:
        orm.current_phase = phase

    async def pause_session(self, _session: object, orm: object) -> None:
        orm.status = "PAUSED"


class TestPersistTurn:
    async def test_backfills_latest_and_inserts_new_row(self) -> None:
        latest = MagicMock(user_recognized_text=None, ai_generated_text="上一个问题")
        repo = _FakeVoiceRepo(latest=latest, count=1)
        orch = _make_orchestrator(tokens=["x"])
        _ready(orch)
        orch._repository = repo  # type: ignore[assignment]

        await orch._persist_turn("我的回答", "新的问题")

        assert latest.user_recognized_text == "我的回答"  # 回填最近未答提问
        assert len(repo.saved) == 1
        row = repo.saved[0]
        assert row.ai_generated_text == "新的问题"
        assert row.user_recognized_text is None  # 已回填到上一行，本行不重复
        assert row.message_type == "DIALOGUE"
        assert row.sequence_num == 2

    async def test_no_latest_stores_answer_on_new_row(self) -> None:
        repo = _FakeVoiceRepo(latest=None, count=0)
        orch = _make_orchestrator()
        _ready(orch)
        orch._repository = repo  # type: ignore[assignment]

        await orch._persist_turn("首答", "开场后的回复")

        assert len(repo.saved) == 1
        row = repo.saved[0]
        assert row.user_recognized_text == "首答"
        assert row.sequence_num == 1


class TestOpeningQuestion:
    async def test_sends_opening_text_and_audio(self) -> None:
        orch = _make_orchestrator(opening="欢迎参加面试。")
        _ready(orch)
        ws = _FakeClientWs()
        await orch._send_opening_question(ws)
        texts = ws.sent_of("text")
        assert texts and texts[0]["text"] == "欢迎参加面试。" and texts[0]["isFinal"] is True
        audio = ws.sent_of("audio_chunk")
        assert audio and audio[-1]["isLast"] is True

    async def test_empty_opening_skipped(self) -> None:
        orch = _make_orchestrator(opening="")
        _ready(orch)
        ws = _FakeClientWs()
        await orch._send_opening_question(ws)
        assert ws.sent == []


def _phase_orm(current: str = "TECH", **enabled: bool) -> MagicMock:
    flags = {"intro_enabled": True, "tech_enabled": True, "project_enabled": True, "hr_enabled": True}
    flags.update(enabled)
    return MagicMock(current_phase=current, **flags)


class TestPhaseTransition:
    async def test_transitions_to_next_enabled_phase(self) -> None:
        orm = _phase_orm("TECH")
        orch = _make_orchestrator()
        _ready(orch)  # context current_phase=TECH, now_ms=0 -> elapsed 0
        orch._repository = _FakeVoiceRepo(orm=orm)  # type: ignore[assignment]
        orch._phase_question_count = 8  # >= TECH max_questions(8) -> 规则 2 切换
        await orch._maybe_transition_phase()
        assert orm.current_phase == "PROJECT"
        assert orch._context is not None and orch._context.current_phase == "PROJECT"
        assert orch._phase_question_count == 0

    async def test_skips_disabled_next_phase(self) -> None:
        orm = _phase_orm("TECH", project_enabled=False)
        orch = _make_orchestrator()
        _ready(orch)
        orch._repository = _FakeVoiceRepo(orm=orm)  # type: ignore[assignment]
        orch._phase_question_count = 8
        await orch._maybe_transition_phase()
        assert orch._context is not None and orch._context.current_phase == "HR"  # PROJECT 禁用 -> HR

    async def test_no_transition_below_thresholds(self) -> None:
        orch = _make_orchestrator()
        _ready(orch)
        orch._phase_question_count = 1
        await orch._maybe_transition_phase()
        assert orch._context is not None and orch._context.current_phase == "TECH"


class TestPauseTimeout:
    async def test_no_action_before_warning(self) -> None:
        orch = _make_orchestrator(now_ms=0.0)
        _ready(orch)
        orch._last_activity_ms = 0.0
        ws = _FakeClientWs()
        stop = await orch._check_pause_timeout(ws)
        assert stop is False
        assert ws.sent == []

    async def test_sends_warning_between_270s_and_300s(self) -> None:
        orch = _make_orchestrator(now_ms=275_000.0)  # 275s: >270s 且 <300s
        _ready(orch)
        orch._last_activity_ms = 0.0
        ws = _FakeClientWs()
        stop = await orch._check_pause_timeout(ws)
        assert stop is False
        assert ws.sent_of("warning")[0]["code"] == "pause_timeout_warning"

    async def test_warning_sent_only_once(self) -> None:
        orch = _make_orchestrator(now_ms=275_000.0)
        _ready(orch)
        orch._last_activity_ms = 0.0
        ws = _FakeClientWs()
        await orch._check_pause_timeout(ws)
        await orch._check_pause_timeout(ws)
        assert len(ws.sent_of("warning")) == 1

    async def test_pauses_and_stops_at_300s(self) -> None:
        orm = _phase_orm("TECH")
        orch = _make_orchestrator(now_ms=305_000.0)  # >300s
        _ready(orch)
        orch._repository = _FakeVoiceRepo(orm=orm)  # type: ignore[assignment]
        orch._last_activity_ms = 0.0
        ws = _FakeClientWs()
        stop = await orch._check_pause_timeout(ws)
        assert stop is True
        assert orm.status == "PAUSED"
        assert ws.sent_of("warning")[0]["code"] == "pause_timeout"


class _BlockingClientWs(_FakeClientWs):
    async def receive_text(self) -> str:
        await asyncio.Event().wait()  # 永不返回，直到被取消
        return ""


class _ReconnectAsr:
    def __init__(self) -> None:
        self.connect_count = 0
        self.closed_count = 0

    async def connect(self) -> None:
        self.connect_count += 1

    async def send_audio(self, _base64_pcm: str) -> None:
        pass

    async def finish(self) -> None:
        pass

    async def close(self) -> None:
        self.closed_count += 1

    async def receive(self) -> AsrTranscript | None:
        raise AsrConnectionClosed("closed", "drop")


class TestAsrReconnect:
    async def test_reconnects_up_to_max_then_stops(self) -> None:
        asr = _ReconnectAsr()
        orch = _make_orchestrator(
            cached_status="IN_PROGRESS", db_orm=_orm(), asr=asr, asr_max_reconnect=2, asr_reconnect_delay=0.0
        )
        ws = _BlockingClientWs()
        await orch.run(ws)
        assert asr.connect_count == 3  # 1 初始 + 2 重连
        assert asr.closed_count == 3
