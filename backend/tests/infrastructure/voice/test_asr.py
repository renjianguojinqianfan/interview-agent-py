"""Qwen ASR Realtime 客户端测试：纯协议构造/解析 + 客户端 IO（注入 fake 连接）。"""

import json

import pytest
from websockets.exceptions import ConnectionClosed

from app.infrastructure.voice.asr import (
    AsrConnectionClosed,
    AsrConnectionConfig,
    AsrError,
    AsrTranscript,
    QwenAsrClient,
    build_audio_append,
    build_connect_uri,
    build_session_finish,
    build_session_update,
    parse_server_event,
)


def _config(**overrides: object) -> AsrConnectionConfig:
    defaults: dict[str, object] = {
        "url": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        "model": "qwen3-asr-flash-realtime",
        "api_key": "sk-test",
        "language": "zh",
        "audio_format": "pcm",
        "sample_rate": 16000,
        "enable_turn_detection": True,
        "turn_detection_type": "server_vad",
        "turn_detection_threshold": 0.0,
        "turn_detection_silence_duration_ms": 2000,
    }
    defaults.update(overrides)
    return AsrConnectionConfig(**defaults)  # type: ignore[arg-type]


class _FakeConn:
    def __init__(self, incoming: list[str] | None = None) -> None:
        self.sent: list[str] = []
        self._incoming = list(incoming or [])
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        if not self._incoming:
            raise ConnectionClosed(None, None)
        return self._incoming.pop(0)

    async def close(self) -> None:
        self.closed = True


def _make_client(incoming: list[str] | None = None) -> tuple[QwenAsrClient, _FakeConn, dict[str, object]]:
    conn = _FakeConn(incoming)
    captured: dict[str, object] = {}

    async def connector(uri: str, headers: dict[str, str]) -> _FakeConn:
        captured["uri"] = uri
        captured["headers"] = headers
        return conn

    client = QwenAsrClient(_config(), connector=connector)
    return client, conn, captured


class TestBuildConnectUri:
    def test_appends_model_query(self) -> None:
        assert build_connect_uri(_config()) == (
            "wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=qwen3-asr-flash-realtime"
        )

    def test_uses_ampersand_when_query_present(self) -> None:
        uri = build_connect_uri(_config(url="wss://host/realtime?x=1"))
        assert uri == "wss://host/realtime?x=1&model=qwen3-asr-flash-realtime"


class TestBuildSessionUpdate:
    def test_includes_audio_and_transcription_config(self) -> None:
        msg = build_session_update(_config())
        assert msg["type"] == "session.update"
        assert msg["event_id"]
        assert msg["session"]["input_audio_format"] == "pcm"
        assert msg["session"]["sample_rate"] == 16000
        assert msg["session"]["input_audio_transcription"]["language"] == "zh"
        assert msg["session"]["turn_detection"]["type"] == "server_vad"
        assert msg["session"]["turn_detection"]["silence_duration_ms"] == 2000

    def test_turn_detection_null_when_disabled(self) -> None:
        msg = build_session_update(_config(enable_turn_detection=False))
        assert msg["session"]["turn_detection"] is None


class TestBuildAudioAndFinish:
    def test_audio_append(self) -> None:
        msg = build_audio_append("QUJD")
        assert msg["type"] == "input_audio_buffer.append"
        assert msg["audio"] == "QUJD"
        assert msg["event_id"]

    def test_session_finish(self) -> None:
        msg = build_session_finish()
        assert msg["type"] == "session.finish"
        assert msg["event_id"]


class TestParseServerEvent:
    def test_partial_combines_text_and_stash(self) -> None:
        result = parse_server_event(
            {
                "type": "conversation.item.input_audio_transcription.text",
                "text": "今天",
                "stash": "天气",
            }
        )
        assert result == AsrTranscript(text="今天天气", is_final=False)

    def test_final_uses_transcript(self) -> None:
        result = parse_server_event(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "今天天气怎么样",
            }
        )
        assert result == AsrTranscript(text="今天天气怎么样", is_final=True)

    def test_ignored_event_returns_none(self) -> None:
        assert parse_server_event({"type": "session.created", "session": {}}) is None

    def test_error_event_raises(self) -> None:
        with pytest.raises(AsrError) as exc:
            parse_server_event({"type": "error", "error": {"code": "invalid_value", "message": "bad"}})
        assert exc.value.code == "invalid_value"

    def test_transcription_failed_raises(self) -> None:
        with pytest.raises(AsrError):
            parse_server_event(
                {
                    "type": "conversation.item.input_audio_transcription.failed",
                    "error": {"code": "asr_failed", "message": "识别失败"},
                }
            )


class TestQwenAsrClient:
    async def test_connect_sends_session_update_with_auth(self) -> None:
        client, conn, captured = _make_client()
        await client.connect()
        assert "model=qwen3-asr-flash-realtime" in str(captured["uri"])
        assert captured["headers"] == {"Authorization": "Bearer sk-test"}
        sent = json.loads(conn.sent[0])
        assert sent["type"] == "session.update"

    async def test_send_audio_emits_append(self) -> None:
        client, conn, _ = _make_client()
        await client.connect()
        await client.send_audio("QUJD")
        append = json.loads(conn.sent[-1])
        assert append["type"] == "input_audio_buffer.append"
        assert append["audio"] == "QUJD"

    async def test_finish_emits_session_finish(self) -> None:
        client, conn, _ = _make_client()
        await client.connect()
        await client.finish()
        assert json.loads(conn.sent[-1])["type"] == "session.finish"

    async def test_receive_parses_partial_then_final(self) -> None:
        incoming = [
            json.dumps({"type": "session.created", "session": {}}),
            json.dumps({"type": "conversation.item.input_audio_transcription.text", "text": "", "stash": "你"}),
            json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "你好"}),
        ]
        client, _, _ = _make_client(incoming)
        await client.connect()
        assert await client.receive() is None  # session.created ignored
        assert await client.receive() == AsrTranscript(text="你", is_final=False)
        assert await client.receive() == AsrTranscript(text="你好", is_final=True)

    async def test_receive_raises_connection_closed_when_exhausted(self) -> None:
        client, _, _ = _make_client(incoming=[])
        await client.connect()
        with pytest.raises(AsrConnectionClosed):
            await client.receive()

    async def test_receive_raises_asr_error_on_error_event(self) -> None:
        incoming = [json.dumps({"type": "error", "error": {"code": "x", "message": "boom"}})]
        client, _, _ = _make_client(incoming)
        await client.connect()
        with pytest.raises(AsrError):
            await client.receive()

    async def test_close_closes_connection(self) -> None:
        client, conn, _ = _make_client()
        await client.connect()
        await client.close()
        assert conn.closed is True

    async def test_send_audio_without_connect_raises(self) -> None:
        client, _, _ = _make_client()
        with pytest.raises(AsrError):
            await client.send_audio("QUJD")
