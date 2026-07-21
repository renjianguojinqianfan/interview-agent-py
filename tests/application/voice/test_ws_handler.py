"""语音面试 WebSocket 编排器测试：握手校验 + 双向泵（单独测各泵避免并发竞态）。"""

import json
from unittest.mock import AsyncMock, MagicMock

from fastapi import WebSocketDisconnect

from app.application.voice.ws_handler import (
    WS_CLOSE_INVALID_STATE,
    WS_CLOSE_SESSION_NOT_FOUND,
    VoiceWsOrchestrator,
)
from app.infrastructure.redis.voice_session_cache import CachedVoiceSession
from app.infrastructure.voice.asr import AsrError, AsrTranscript


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


class _FakeAsr:
    def __init__(self, events: list[object] | None = None) -> None:
        self._events = list(events or [])
        self.connected = False
        self.closed = False
        self.finished = False
        self.audio: list[str] = []

    async def connect(self) -> None:
        self.connected = True

    async def send_audio(self, base64_pcm: str) -> None:
        self.audio.append(base64_pcm)

    async def finish(self) -> None:
        self.finished = True

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


def _cached(status: str) -> CachedVoiceSession:
    return CachedVoiceSession(
        session_id="1",
        user_id="default",
        role_type="Java面试官",
        skill_id="java-backend",
        difficulty="mid",
        current_phase="INTRO",
        status=status,
        resume_id=None,
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
    db_status: str | None = None,
    asr: _FakeAsr | None = None,
) -> VoiceWsOrchestrator:
    cache = MagicMock()
    cache.get_session = AsyncMock(return_value=_cached(cached_status) if cached_status else None)
    repository = MagicMock()
    db_orm = MagicMock(status=db_status) if db_status else None
    repository.get_by_id = AsyncMock(return_value=db_orm)
    loader = MagicMock()
    loader.load = AsyncMock(return_value=MagicMock())
    return VoiceWsOrchestrator(
        session_id=1,
        cache=cache,
        repository=repository,
        session_factory=_make_session_factory(),
        asr_config_loader=loader,
        asr_client_factory=lambda _config: asr or _FakeAsr(),
    )


class TestHandshake:
    async def test_closes_when_session_not_found(self) -> None:
        orch = _make_orchestrator(cached_status=None, db_status=None)
        ws = _FakeClientWs()
        await orch.run(ws)
        assert ws.closed_code == WS_CLOSE_SESSION_NOT_FOUND
        assert ws.accepted is False

    async def test_closes_when_status_not_in_progress(self) -> None:
        orch = _make_orchestrator(cached_status="PAUSED")
        ws = _FakeClientWs()
        await orch.run(ws)
        assert ws.closed_code == WS_CLOSE_INVALID_STATE
        assert ws.accepted is False

    async def test_falls_back_to_db_when_cache_miss(self) -> None:
        orch = _make_orchestrator(cached_status=None, db_status="IN_PROGRESS")
        asr = _FakeAsr()
        orch._asr_client_factory = lambda _config: asr
        ws = _FakeClientWs()
        await orch.run(ws)
        assert ws.accepted is True
        assert asr.connected is True
        assert asr.closed is True

    async def test_accepts_and_connects_when_in_progress(self) -> None:
        asr = _FakeAsr()
        orch = _make_orchestrator(cached_status="IN_PROGRESS", asr=asr)
        ws = _FakeClientWs()
        await orch.run(ws)
        assert ws.accepted is True
        assert asr.connected is True
        assert asr.closed is True


class TestAsrToClient:
    async def test_partial_pushed_as_subtitle_non_final(self) -> None:
        orch = _make_orchestrator()
        ws = _FakeClientWs()
        asr = _FakeAsr(events=[AsrTranscript(text="今天", is_final=False)])
        await orch._asr_to_client(ws, asr)
        assert ws.sent == [{"type": "subtitle", "text": "今天", "isFinal": False}]
        assert orch.final_segments == []

    async def test_final_accumulated_without_subtitle(self) -> None:
        orch = _make_orchestrator()
        ws = _FakeClientWs()
        asr = _FakeAsr(events=[AsrTranscript(text="今天天气", is_final=True)])
        await orch._asr_to_client(ws, asr)
        assert ws.sent == []
        assert orch.final_segments == ["今天天气"]

    async def test_none_event_ignored(self) -> None:
        orch = _make_orchestrator()
        ws = _FakeClientWs()
        asr = _FakeAsr(events=[None])
        await orch._asr_to_client(ws, asr)
        assert ws.sent == []

    async def test_asr_error_sent_as_error_message(self) -> None:
        orch = _make_orchestrator()
        ws = _FakeClientWs()
        asr = _FakeAsr(events=[AsrError("bad", "boom"), None])
        await orch._asr_to_client(ws, asr)
        assert ws.sent[0] == {"type": "error", "code": "bad", "message": "boom"}


class TestClientToAsr:
    async def test_audio_forwarded_to_asr(self) -> None:
        orch = _make_orchestrator()
        ws = _FakeClientWs(incoming=[json.dumps({"type": "audio", "data": "QUJD"})])
        asr = _FakeAsr()
        await orch._client_to_asr(ws, asr)
        assert asr.audio == ["QUJD"]

    async def test_control_finish_triggers_asr_finish(self) -> None:
        orch = _make_orchestrator()
        ws = _FakeClientWs(incoming=[json.dumps({"type": "control", "action": "finish"})])
        asr = _FakeAsr()
        await orch._client_to_asr(ws, asr)
        assert asr.finished is True

    async def test_bad_message_sends_error(self) -> None:
        orch = _make_orchestrator()
        ws = _FakeClientWs(incoming=["not-json"])
        asr = _FakeAsr()
        await orch._client_to_asr(ws, asr)
        assert ws.sent[0]["type"] == "error"
        assert ws.sent[0]["code"] == "bad_message"
