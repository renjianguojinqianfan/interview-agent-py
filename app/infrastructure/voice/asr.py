"""Qwen3 Realtime ASR WebSocket 出站客户端。

对接 DashScope Qwen-ASR Realtime（OpenAI Realtime 风格协议）：
- 连接 `wss://.../api-ws/v1/realtime?model=<model>`，Header `Authorization: Bearer <api_key>`
- 首帧 `session.update` 配置 pcm / sample_rate / language / server_vad
- `input_audio_buffer.append` 流式发送 base64 PCM（服务端不 ack）
- 服务端事件：
  - `conversation.item.input_audio_transcription.text`（partial：text 已确认前缀 + stash 临时后缀）
  - `conversation.item.input_audio_transcription.completed`（final：transcript）
  - `error` / `conversation.item.input_audio_transcription.failed`（错误）

协议来源（官方文档）：
- 客户端事件 https://help.aliyun.com/zh/model-studio/qwen-asr-realtime-client-events
- 服务端事件 https://help.aliyun.com/zh/model-studio/qwen-asr-realtime-server-events

纯协议构造/解析函数（build_*/parse_server_event）与 IO 客户端（QwenAsrClient）分离，
connector 可注入以便测试。#15 仅覆盖 partial->字幕、final->mergeBuffer；重连（#17）不在本文件范围。
"""

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

_EVENT_SESSION_UPDATE = "session.update"
_EVENT_AUDIO_APPEND = "input_audio_buffer.append"
_EVENT_SESSION_FINISH = "session.finish"
_EVENT_TRANSCRIPTION_TEXT = "conversation.item.input_audio_transcription.text"
_EVENT_TRANSCRIPTION_COMPLETED = "conversation.item.input_audio_transcription.completed"
_EVENT_TRANSCRIPTION_FAILED = "conversation.item.input_audio_transcription.failed"
_EVENT_ERROR = "error"


@dataclass(frozen=True)
class AsrConnectionConfig:
    """ASR 连接参数（api_key 为明文，由上游从加密配置解密后传入）。"""

    url: str
    model: str
    api_key: str
    language: str
    audio_format: str
    sample_rate: int
    enable_turn_detection: bool
    turn_detection_type: str
    turn_detection_threshold: float
    turn_detection_silence_duration_ms: int


@dataclass(frozen=True)
class AsrTranscript:
    """ASR 转写结果。is_final=False 为实时预览（partial），True 为最终结果（final）。"""

    text: str
    is_final: bool


class AsrError(RuntimeError):
    """ASR 服务返回的错误事件。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class AsrConnectionClosed(AsrError):
    """ASR WebSocket 连接已关闭（正常或异常）。"""


class AsrConnection(Protocol):
    """出站 ASR WebSocket 连接的最小契约（便于注入与测试）。"""

    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


AsrConnector = Callable[[str, dict[str, str]], Awaitable[AsrConnection]]


def _new_event_id() -> str:
    return f"event_{uuid.uuid4().hex}"


def build_connect_uri(config: AsrConnectionConfig) -> str:
    """构造带 model 查询参数的连接 URI。"""
    separator = "&" if "?" in config.url else "?"
    return f"{config.url}{separator}model={config.model}"


def build_session_update(config: AsrConnectionConfig) -> dict[str, Any]:
    """构造首帧 session.update 配置消息。turn_detection 为 None 时关闭 VAD。"""
    turn_detection: dict[str, Any] | None = None
    if config.enable_turn_detection:
        turn_detection = {
            "type": config.turn_detection_type,
            "threshold": config.turn_detection_threshold,
            "silence_duration_ms": config.turn_detection_silence_duration_ms,
        }
    return {
        "type": _EVENT_SESSION_UPDATE,
        "event_id": _new_event_id(),
        "session": {
            "input_audio_format": config.audio_format,
            "sample_rate": config.sample_rate,
            "input_audio_transcription": {"language": config.language},
            "turn_detection": turn_detection,
        },
    }


def build_audio_append(base64_pcm: str) -> dict[str, Any]:
    """构造 input_audio_buffer.append 音频块消息。"""
    return {
        "type": _EVENT_AUDIO_APPEND,
        "event_id": _new_event_id(),
        "audio": base64_pcm,
    }


def build_session_finish() -> dict[str, Any]:
    """构造 session.finish 结束消息。"""
    return {"type": _EVENT_SESSION_FINISH, "event_id": _new_event_id()}


def parse_server_event(raw: dict[str, Any]) -> AsrTranscript | None:
    """解析服务端事件为 AsrTranscript；非转写事件返回 None；错误事件抛 AsrError。"""
    event_type = raw.get("type")
    if event_type == _EVENT_TRANSCRIPTION_TEXT:
        # Qwen 实时预览：text 已确认前缀 + stash 临时后缀，拼接为当前预览文本
        text = str(raw.get("text") or "")
        stash = str(raw.get("stash") or "")
        return AsrTranscript(text=f"{text}{stash}", is_final=False)
    if event_type == _EVENT_TRANSCRIPTION_COMPLETED:
        return AsrTranscript(text=str(raw.get("transcript") or ""), is_final=True)
    if event_type in (_EVENT_ERROR, _EVENT_TRANSCRIPTION_FAILED):
        error = raw.get("error") or {}
        code = str(error.get("code") or "asr_error")
        message = str(error.get("message") or "ASR 服务错误")
        raise AsrError(code, message)
    return None


async def _default_connect(uri: str, headers: dict[str, str]) -> AsrConnection:
    import websockets

    conn = await websockets.connect(uri, additional_headers=headers)
    return cast(AsrConnection, conn)


class QwenAsrClient:
    """Qwen ASR Realtime WebSocket 客户端：连接、发送音频、迭代转写结果。"""

    def __init__(self, config: AsrConnectionConfig, connector: AsrConnector | None = None) -> None:
        self._config = config
        self._connector = connector or _default_connect
        self._conn: AsrConnection | None = None

    async def connect(self) -> None:
        uri = build_connect_uri(self._config)
        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        self._conn = await self._connector(uri, headers)
        await self._send(build_session_update(self._config))

    async def send_audio(self, base64_pcm: str) -> None:
        await self._send(build_audio_append(base64_pcm))

    async def finish(self) -> None:
        if self._conn is not None:
            await self._send(build_session_finish())

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def receive(self) -> AsrTranscript | None:
        """接收并解析一条服务端事件。转写事件返回 AsrTranscript，忽略事件返回 None，
        错误事件抛 AsrError，连接关闭抛 AsrConnectionClosed。"""
        conn = self._require_conn()
        try:
            raw = await conn.recv()
        except ConnectionClosed as e:
            raise AsrConnectionClosed("connection_closed", "ASR 连接已关闭") from e
        message = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("ASR 事件 JSON 解析失败，跳过")
            return None
        if not isinstance(event, dict):
            return None
        return parse_server_event(cast(dict[str, Any], event))

    def _require_conn(self) -> AsrConnection:
        if self._conn is None:
            raise AsrError("not_connected", "ASR 连接未建立")
        return self._conn

    async def _send(self, payload: dict[str, Any]) -> None:
        conn = self._require_conn()
        await conn.send(json.dumps(payload, ensure_ascii=False))
