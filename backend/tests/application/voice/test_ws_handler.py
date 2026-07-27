"""语音面试 WebSocket 编排器测试：握手 + ASR 桥接 + LLM 回合 + 句子级 TTS + 回声抑制。

各泵/回合单独测试以避免并发竞态；LLM/TTS/时钟均以 fake 注入。
"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
from fastapi import WebSocketDisconnect

from app.application.voice.ws_handler import (
    WS_CLOSE_INVALID_STATE,
    WS_CLOSE_SESSION_NOT_FOUND,
    VoiceWsOrchestrator,
)
from app.domain.errors import ErrorCode
from app.infrastructure.redis.voice_session_cache import CachedVoiceSession
from app.infrastructure.voice.asr import AsrAuthError, AsrConnectionClosed, AsrTranscript
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


_ERR_REQUEST = httpx.Request("POST", "https://dashscope.example/api")


class _RaisingDialogueLlm:
    """stream_reply 在流式迭代中抛出指定异常（模拟 LLM SDK 错误路径，8.6）。"""

    def __init__(self, exc: BaseException, tokens: list[str] | None = None) -> None:
        self._exc = exc
        self._tokens = tokens or []

    def stream_reply(self, _context: object, _history: str, _answer: str) -> AsyncIterator[str]:
        exc = self._exc
        tokens = self._tokens

        async def _gen() -> AsyncIterator[str]:
            for token in tokens:
                yield token
            raise exc

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
        role_type="r", skill_id="s", difficulty="mid", current_phase="TECH", custom_jd_text=None, llm_provider=None
    )
    orch._tts_config = MagicMock()


class TestHandshake:
    async def test_closes_when_session_not_found(self) -> None:
        orch = _make_orchestrator(cached_status=None, db_orm=None)
        ws = _FakeClientWs()
        await orch.run(ws)
        assert ws.closed_code == WS_CLOSE_SESSION_NOT_FOUND
        # #50：必须先 accept 再 close，否则 Starlette 以 HTTP 403 拒绝握手，客户端拿不到 4004
        assert ws.accepted is True

    async def test_closes_when_status_not_in_progress(self) -> None:
        orch = _make_orchestrator(cached_status="PAUSED")
        ws = _FakeClientWs()
        await orch.run(ws)
        assert ws.closed_code == WS_CLOSE_INVALID_STATE
        assert ws.accepted is True

    async def test_accepts_and_connects_when_in_progress(self) -> None:
        asr = _FakeAsr()
        orch = _make_orchestrator(cached_status="IN_PROGRESS", db_orm=_orm(), asr=asr)
        ws = _FakeClientWs()
        await orch.run(ws)
        assert ws.accepted is True
        assert asr.connected is True
        assert asr.closed is True

    async def test_asr_auth_error_sends_error_without_reconnect(self) -> None:
        """#50：ASR 鉴权失败（如 DashScope 401）直接推送 error 消息并终止，不重连。"""

        class _AuthFailAsr(_FakeAsr):
            def __init__(self) -> None:
                super().__init__()
                self.connect_calls = 0

            async def connect(self) -> None:
                self.connect_calls += 1
                raise AsrAuthError("asr_auth_failed", "语音服务鉴权失败")

        asr = _AuthFailAsr()
        orch = _make_orchestrator(cached_status="IN_PROGRESS", db_orm=_orm(), asr=asr)
        ws = _FakeClientWs()
        await orch.run(ws)
        errors = ws.sent_of("error")
        assert len(errors) == 1
        assert errors[0]["code"] == "asr_auth_failed"
        assert asr.connect_calls == 1  # 不重连
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
        assert [m for m in text_msgs if not m["final"]]  # 流式（累积全文）
        finals = [m for m in text_msgs if m["final"]]
        assert finals and finals[-1]["content"] == "你好。请介绍"

        audio_msgs = ws.sent_of("audio_chunk")
        # audio_chunk.data 必须为带 44 字节 WAV 头的 base64（前端 handleAudioChunk 跳过前 44 字节取 PCM）
        payloads = [base64.b64decode(m["data"]) for m in audio_msgs if m["data"]]
        assert payloads and all(p[:4] == b"RIFF" and p[8:12] == b"WAVE" for p in payloads)
        assert any(p[44:] == b"ABC" for p in payloads)  # QUJD -> b"ABC" 原始 PCM 保留在头之后
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


class TestCommitTurnAiError:
    """8.6：LLM 流式回复抛 AI SDK 异常 -> ErrorMessage 细分错误码；非 AI 异常 -> llm_error。"""

    async def test_rate_limit_sends_ai_error_code(self) -> None:
        orch = _make_orchestrator()
        _ready(orch)
        exc = openai.RateLimitError("rate", response=httpx.Response(429, request=_ERR_REQUEST), body=None)
        orch._dialogue_llm = _RaisingDialogueLlm(exc)  # type: ignore[assignment]
        orch._final_segments = ["我的回答"]
        ws = _FakeClientWs()
        await orch._commit_turn(ws)
        errors = ws.sent_of("error")
        assert errors and errors[-1]["code"] == str(ErrorCode.AI_RATE_LIMIT_EXCEEDED.code)

    async def test_non_ai_error_sends_llm_error(self) -> None:
        orch = _make_orchestrator()
        _ready(orch)
        orch._dialogue_llm = _RaisingDialogueLlm(RuntimeError("boom"))  # type: ignore[assignment]
        orch._final_segments = ["我的回答"]
        ws = _FakeClientWs()
        await orch._commit_turn(ws)
        errors = ws.sent_of("error")
        assert errors and errors[-1]["code"] == "llm_error"


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
        assert texts and texts[0]["content"] == "欢迎参加面试。" and texts[0]["final"] is True
        audio = ws.sent_of("audio_chunk")
        assert audio and audio[-1]["isLast"] is True
        # #54：开场音频链末尾同样随发 audio_complete
        assert any(m["action"] == "audio_complete" for m in ws.sent_of("control"))

    async def test_empty_opening_skipped(self) -> None:
        orch = _make_orchestrator(opening="")
        _ready(orch)
        ws = _FakeClientWs()
        await orch._send_opening_question(ws)
        assert ws.sent == []


class _CountingVoiceRepo(_FakeVoiceRepo):
    """计数随落库增长的假仓储：模拟真实表状态跨多次连接演进（#57 重连场景）。"""

    def __init__(self, initial_count: int = 0) -> None:
        super().__init__(latest=None, count=initial_count)
        self._initial_count = initial_count

    async def count_messages_by_session(self, _session: object, _pk: int) -> int:
        return self._initial_count + len(self.saved)


class _CountRaisingVoiceRepo(_FakeVoiceRepo):
    """count 查询抛异常的假仓储（#57 最佳努力回退路径）。always_fail=False 时仅首调失败。"""

    count_calls: int

    def __init__(self, always_fail: bool = False) -> None:
        super().__init__(latest=None, count=0)
        self.count_calls = 0
        self._always_fail = always_fail

    async def count_messages_by_session(self, _session: object, _pk: int) -> int:
        self.count_calls += 1
        if self._always_fail or self.count_calls == 1:
            raise RuntimeError("db down")
        return 0


class TestOpeningPersistIdempotent:
    """#57：开场白仅首连落库；重连（消息表非空）只投递不持久化。"""

    async def test_first_connection_persists_once(self) -> None:
        repo = _CountingVoiceRepo(initial_count=0)
        orch = _make_orchestrator(opening="欢迎参加面试。")
        _ready(orch)
        orch._repository = repo  # type: ignore[assignment]
        await orch._send_opening_question(_FakeClientWs())
        assert len(repo.saved) == 1
        assert repo.saved[0].ai_generated_text == "欢迎参加面试。"

    async def test_reconnect_does_not_persist_again(self) -> None:
        repo = _CountingVoiceRepo(initial_count=1)  # 首连已落过开场白
        orch = _make_orchestrator(opening="欢迎参加面试。")
        _ready(orch)
        orch._repository = repo  # type: ignore[assignment]
        await orch._send_opening_question(_FakeClientWs())
        assert repo.saved == []

    async def test_reconnect_still_delivers_text_and_audio(self) -> None:
        """去重只作用于落库，投递不受影响（验收项）。"""
        repo = _CountingVoiceRepo(initial_count=1)
        orch = _make_orchestrator(opening="欢迎参加面试。")
        _ready(orch)
        orch._repository = repo  # type: ignore[assignment]
        ws = _FakeClientWs()
        await orch._send_opening_question(ws)
        texts = ws.sent_of("text")
        assert texts and texts[0]["content"] == "欢迎参加面试。" and texts[0]["final"] is True
        assert ws.sent_of("audio_chunk")[-1]["isLast"] is True
        assert any(m["action"] == "audio_complete" for m in ws.sent_of("control"))

    async def test_two_reconnects_total_one_row(self) -> None:
        """首连 + 重连两次，落库总数仍为 1（验收项：重连两次场景）。

        每轮新建 orchestrator（生产语义：每次连接实例化一次），共享同一 repo 模拟跨连接表状态。
        """
        repo = _CountingVoiceRepo(initial_count=0)
        for _ in range(3):  # 首连 + 2 次重连
            orch = _make_orchestrator(opening="欢迎参加面试。")
            _ready(orch)
            orch._repository = repo  # type: ignore[assignment]
            await orch._send_opening_question(_FakeClientWs())
        assert len(repo.saved) == 1

    async def test_count_query_failure_falls_back_to_persist(self) -> None:
        """计数查询失败按首连处理（回退到尝试落库；本例 _persist_turn 内二次查询恢复故成功）。"""
        repo = _CountRaisingVoiceRepo()
        orch = _make_orchestrator(opening="欢迎参加面试。")
        _ready(orch)
        orch._repository = repo  # type: ignore[assignment]
        await orch._send_opening_question(_FakeClientWs())
        assert len(repo.saved) == 1

    async def test_db_fully_down_degrades_silently(self) -> None:
        """DB 全程不可用：回退分支进入 _persist_turn 后同样失败被吞，一条不落且不上抛（最佳努力契约）。"""
        repo = _CountRaisingVoiceRepo(always_fail=True)
        orch = _make_orchestrator(opening="欢迎参加面试。")
        _ready(orch)
        orch._repository = repo  # type: ignore[assignment]
        await orch._send_opening_question(_FakeClientWs())  # 不抛异常
        assert repo.saved == []


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
        # #54：暂停超时事件走 control 消息（前端 onControl 分支处理）
        assert ws.sent_of("control")[0]["action"] == "pause_timeout_warning"

    async def test_warning_sent_only_once(self) -> None:
        orch = _make_orchestrator(now_ms=275_000.0)
        _ready(orch)
        orch._last_activity_ms = 0.0
        ws = _FakeClientWs()
        await orch._check_pause_timeout(ws)
        await orch._check_pause_timeout(ws)
        assert len(ws.sent_of("control")) == 1

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
        assert ws.sent_of("control")[0]["action"] == "pause_timeout"


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


class TestServerControlContract:
    """#54：服务端出站控制消息契约（前端复用 Java 契约：缺 asr_ready 即麦克风永久置灰）。"""

    async def test_sends_asr_ready_after_connect(self) -> None:
        asr = _FakeAsr()
        orch = _make_orchestrator(cached_status="IN_PROGRESS", db_orm=_orm(), asr=asr)
        ws = _FakeClientWs()
        await orch.run(ws)
        actions = [m["action"] for m in ws.sent_of("control")]
        assert "asr_ready" in actions

    async def test_sends_asr_reconnecting_then_ready_again(self) -> None:
        asr = _ReconnectAsr()
        orch = _make_orchestrator(
            cached_status="IN_PROGRESS", db_orm=_orm(), asr=asr, asr_max_reconnect=1, asr_reconnect_delay=0.0
        )
        ws = _BlockingClientWs()
        await orch.run(ws)
        actions = [m["action"] for m in ws.sent_of("control")]
        assert "asr_reconnecting" in actions
        assert actions.count("asr_ready") == 2  # 初始连接 + 重连成功后重新解锁

    async def test_audio_complete_follows_last_chunk(self) -> None:
        orch = _make_orchestrator(tokens=["你好。"])
        _ready(orch)
        orch._final_segments = ["我叫张三"]
        ws = _FakeClientWs()
        await orch._commit_turn(ws)
        last_chunk_idx = max(i for i, m in enumerate(ws.sent) if m["type"] == "audio_chunk" and m["isLast"])
        followers = [(m["type"], m.get("action")) for m in ws.sent[last_chunk_idx + 1 :]]
        assert ("control", "audio_complete") in followers

    async def test_final_transcript_pushed_as_final_subtitle(self) -> None:
        """final 转写须下发 isFinal=true 字幕（前端据此把用户发言写入对话实录）。"""
        orch = _make_orchestrator(tokens=["好的。"])
        _ready(orch)
        ws = _FakeClientWs()
        await orch._on_final_transcript(ws, "a" * 25)
        finals = [m for m in ws.sent_of("subtitle") if m["isFinal"]]
        assert finals and finals[0]["text"] == "a" * 25

    async def test_text_streaming_cumulative_with_content_field(self) -> None:
        """text 出站 JSON 键须为 content/final，且流式为累积全文（前端 setAiText 不做拼接）。"""
        orch = _make_orchestrator(tokens=["你好", "。", "请介绍"])
        _ready(orch)
        orch._final_segments = ["我叫张三"]
        ws = _FakeClientWs()
        await orch._commit_turn(ws)
        text_msgs = ws.sent_of("text")
        partials = [m["content"] for m in text_msgs if not m["final"]]
        assert partials == ["你好", "你好。", "你好。请介绍"]
        assert text_msgs[-1] == {"type": "text", "content": "你好。请介绍", "final": True}
