"""Qwen TTS Realtime 客户端测试：纯协议构造/解析 + 客户端 IO（注入 fake 连接）。"""

import json

import pytest
from websockets.exceptions import ConnectionClosed

from app.infrastructure.voice.tts import (
    QwenTtsClient,
    TtsConnectionClosed,
    TtsConnectionConfig,
    TtsError,
    TtsEvent,
    build_text_append,
    build_text_commit,
    build_tts_session_finish,
    build_tts_session_update,
    parse_tts_server_event,
)


def _config(**overrides: object) -> TtsConnectionConfig:
    defaults: dict[str, object] = {
        "url": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        "model": "qwen3-tts-flash-realtime",
        "api_key": "sk-test",
        "voice": "Cherry",
        "mode": "commit",
        "response_format": "pcm",
        "sample_rate": 24000,
        "speech_rate": 1.0,
        "volume": 60,
        "language_type": "Chinese",
    }
    defaults.update(overrides)
    return TtsConnectionConfig(**defaults)  # type: ignore[arg-type]


class _FakeConn:
    def __init__(self, incoming: list[str] | None = None) -> None:
        self.sent: list[str] = []
        self._incoming = list(incoming or [])

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        if not self._incoming:
            raise ConnectionClosed(None, None)
        return self._incoming.pop(0)

    async def close(self) -> None:
        pass


def _make_client(incoming: list[str] | None = None) -> tuple[QwenTtsClient, _FakeConn, dict[str, object]]:
    conn = _FakeConn(incoming)
    captured: dict[str, object] = {}

    async def connector(uri: str, headers: dict[str, str]) -> _FakeConn:
        captured["uri"] = uri
        captured["headers"] = headers
        return conn

    return QwenTtsClient(_config(), connector=connector), conn, captured


class TestBuildMessages:
    def test_session_update(self) -> None:
        msg = build_tts_session_update(_config())
        assert msg["type"] == "session.update"
        assert msg["session"]["voice"] == "Cherry"
        assert msg["session"]["response_format"] == "pcm"
        assert msg["session"]["sample_rate"] == 24000
        assert msg["session"]["speech_rate"] == 1.0
        assert msg["session"]["volume"] == 60

    def test_text_append(self) -> None:
        msg = build_text_append("你好")
        assert msg["type"] == "input_text_buffer.append"
        assert msg["text"] == "你好"

    def test_text_commit(self) -> None:
        assert build_text_commit()["type"] == "input_text_buffer.commit"

    def test_session_finish(self) -> None:
        assert build_tts_session_finish()["type"] == "session.finish"


class TestParseTtsServerEvent:
    def test_audio_delta(self) -> None:
        result = parse_tts_server_event({"type": "response.audio.delta", "delta": "QUJD"})
        assert result == TtsEvent(audio_base64="QUJD", done=False)

    def test_audio_done(self) -> None:
        result = parse_tts_server_event({"type": "response.audio.done"})
        assert result == TtsEvent(audio_base64=None, done=True)

    def test_ignored_event(self) -> None:
        assert parse_tts_server_event({"type": "session.created", "session": {}}) is None

    def test_error_raises(self) -> None:
        with pytest.raises(TtsError) as exc:
            parse_tts_server_event({"type": "error", "error": {"code": "bad", "message": "boom"}})
        assert exc.value.code == "bad"


class TestQwenTtsClient:
    async def test_connect_sends_session_update_with_auth(self) -> None:
        client, conn, captured = _make_client()
        await client.connect()
        assert "model=qwen3-tts-flash-realtime" in str(captured["uri"])
        assert captured["headers"] == {"Authorization": "Bearer sk-test"}
        assert json.loads(conn.sent[0])["type"] == "session.update"

    async def test_synthesize_sends_append_then_commit(self) -> None:
        client, conn, _ = _make_client()
        await client.connect()
        await client.synthesize("你好")
        assert json.loads(conn.sent[-2])["type"] == "input_text_buffer.append"
        assert json.loads(conn.sent[-2])["text"] == "你好"
        assert json.loads(conn.sent[-1])["type"] == "input_text_buffer.commit"

    async def test_receive_parses_delta_then_done(self) -> None:
        incoming = [
            json.dumps({"type": "session.created", "session": {}}),
            json.dumps({"type": "response.audio.delta", "delta": "QUJD"}),
            json.dumps({"type": "response.audio.done"}),
        ]
        client, _, _ = _make_client(incoming)
        await client.connect()
        assert await client.receive() is None
        assert await client.receive() == TtsEvent(audio_base64="QUJD", done=False)
        assert await client.receive() == TtsEvent(audio_base64=None, done=True)

    async def test_receive_raises_connection_closed(self) -> None:
        client, _, _ = _make_client(incoming=[])
        await client.connect()
        with pytest.raises(TtsConnectionClosed):
            await client.receive()

    async def test_synthesize_without_connect_raises(self) -> None:
        client, _, _ = _make_client()
        with pytest.raises(TtsError):
            await client.synthesize("你好")
