"""语音面试 WebSocket 端点集成测试：覆盖握手拒绝与字幕流转（覆盖端点接线）。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_voice_ws_orchestrator_factory
from app.application.voice.ws_handler import VoiceWsOrchestrator
from app.infrastructure.redis.voice_session_cache import CachedVoiceSession
from app.infrastructure.voice.asr import AsrConnectionClosed, AsrTranscript
from app.main import app

client = TestClient(app)


class _FakeAsr:
    def __init__(self, events: list[AsrTranscript]) -> None:
        self._events = list(events)
        self.closed = False

    async def connect(self) -> None:
        pass

    async def send_audio(self, base64_pcm: str) -> None:
        pass

    async def finish(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True

    async def receive(self) -> AsrTranscript | None:
        if not self._events:
            raise AsrConnectionClosed("closed", "connection closed")
        return self._events.pop(0)


def _make_session_factory() -> MagicMock:
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


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


def _orm() -> MagicMock:
    return MagicMock(
        status="IN_PROGRESS",
        role_type="Java面试官",
        skill_id="java-backend",
        difficulty="mid",
        current_phase="TECH",
        custom_jd_text=None,
        llm_provider=None,
    )


def _factory_override(status: str | None, events: list[AsrTranscript]):
    cache = MagicMock()
    cache.get_session = AsyncMock(return_value=_cached(status) if status else None)
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=_orm() if status else None)
    loader = MagicMock()
    loader.load = AsyncMock(return_value=MagicMock())
    session_factory = _make_session_factory()

    def _build(session_id: int) -> VoiceWsOrchestrator:
        return VoiceWsOrchestrator(
            session_id=session_id,
            cache=cache,
            repository=repository,
            session_factory=session_factory,
            asr_config_loader=loader,
            asr_client_factory=lambda _config: _FakeAsr(list(events)),
            tts_config_loader=loader,
            tts_client_factory=lambda _config: MagicMock(),
            dialogue_llm=MagicMock(),
        )

    return lambda: _build


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


def test_rejects_when_session_not_found() -> None:
    app.dependency_overrides[get_voice_ws_orchestrator_factory] = _factory_override(None, [])
    with pytest.raises(WebSocketDisconnect):  # noqa: SIM117
        with client.websocket_connect("/ws/voice-interview/1") as ws:
            ws.receive_text()


def test_streams_subtitle_for_partial_transcript() -> None:
    events = [AsrTranscript(text="今天", is_final=False)]
    app.dependency_overrides[get_voice_ws_orchestrator_factory] = _factory_override("IN_PROGRESS", events)
    with client.websocket_connect("/ws/voice-interview/1") as ws:
        msg = json.loads(ws.receive_text())
        assert msg == {"type": "subtitle", "text": "今天", "isFinal": False}
