"""Qwen3 Realtime TTS WebSocket 出站客户端。

对接 DashScope Qwen-TTS Realtime（OpenAI Realtime 风格），复用 asr_url 端点，仅 model 不同：
- 连接 `wss://.../api-ws/v1/realtime?model=<tts_model>`，Header `Authorization: Bearer <api_key>`
- 首帧 `session.update` 配置 voice/mode/response_format(pcm)/sample_rate/speech_rate/volume/language_type
- `input_text_buffer.append`(text) + `input_text_buffer.commit` 触发合成
- 服务端事件：`response.audio.delta`(base64 PCM) / `response.audio.done` / `error`

协议来源（官方文档）：
- 客户端事件 https://help.aliyun.com/zh/model-studio/qwen-tts-realtime-client-events
- 服务端事件 https://help.aliyun.com/zh/model-studio/qwen-tts-realtime-server-events

纯协议构造/解析（build_*/parse_tts_server_event）与 IO 客户端（QwenTtsClient）分离，
connector 可注入以便测试。连接原语复用 realtime_ws。
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, cast

from websockets.exceptions import ConnectionClosed

from app.infrastructure.voice.realtime_ws import (
    RealtimeConnection,
    RealtimeConnector,
    build_realtime_uri,
    default_connect,
    new_event_id,
)

logger = logging.getLogger(__name__)

_EVENT_SESSION_UPDATE = "session.update"
_EVENT_TEXT_APPEND = "input_text_buffer.append"
_EVENT_TEXT_COMMIT = "input_text_buffer.commit"
_EVENT_SESSION_FINISH = "session.finish"
_EVENT_AUDIO_DELTA = "response.audio.delta"
_EVENT_AUDIO_DONE = "response.audio.done"
_EVENT_ERROR = "error"


@dataclass(frozen=True)
class TtsConnectionConfig:
    """TTS 连接参数（api_key 为明文；url 复用 asr_url）。"""

    url: str
    model: str
    api_key: str
    voice: str
    mode: str
    response_format: str
    sample_rate: int
    speech_rate: float
    volume: int
    language_type: str


@dataclass(frozen=True)
class TtsEvent:
    """TTS 服务端事件解析结果。audio_base64 非空为音频块；done=True 为本次合成结束。"""

    audio_base64: str | None
    done: bool


class TtsError(RuntimeError):
    """TTS 服务返回的错误事件。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class TtsConnectionClosed(TtsError):
    """TTS WebSocket 连接已关闭（正常或异常）。"""


def build_tts_session_update(config: TtsConnectionConfig) -> dict[str, Any]:
    """构造首帧 session.update 配置消息。"""
    return {
        "type": _EVENT_SESSION_UPDATE,
        "event_id": new_event_id(),
        "session": {
            "voice": config.voice,
            "mode": config.mode,
            "language_type": config.language_type,
            "response_format": config.response_format,
            "sample_rate": config.sample_rate,
            "speech_rate": config.speech_rate,
            "volume": config.volume,
        },
    }


def build_text_append(text: str) -> dict[str, Any]:
    """构造 input_text_buffer.append 文本消息。"""
    return {"type": _EVENT_TEXT_APPEND, "event_id": new_event_id(), "text": text}


def build_text_commit() -> dict[str, Any]:
    """构造 input_text_buffer.commit 提交消息（触发合成）。"""
    return {"type": _EVENT_TEXT_COMMIT, "event_id": new_event_id()}


def build_tts_session_finish() -> dict[str, Any]:
    """构造 session.finish 结束消息。"""
    return {"type": _EVENT_SESSION_FINISH, "event_id": new_event_id()}


def parse_tts_server_event(raw: dict[str, Any]) -> TtsEvent | None:
    """解析服务端事件为 TtsEvent；无关事件返回 None；错误事件抛 TtsError。"""
    event_type = raw.get("type")
    if event_type == _EVENT_AUDIO_DELTA:
        return TtsEvent(audio_base64=str(raw.get("delta") or ""), done=False)
    if event_type == _EVENT_AUDIO_DONE:
        return TtsEvent(audio_base64=None, done=True)
    if event_type == _EVENT_ERROR:
        error = raw.get("error") or {}
        code = str(error.get("code") or "tts_error")
        message = str(error.get("message") or "TTS 服务错误")
        raise TtsError(code, message)
    return None


class QwenTtsClient:
    """Qwen TTS Realtime WebSocket 客户端：连接、送文本、迭代音频块。"""

    def __init__(self, config: TtsConnectionConfig, connector: RealtimeConnector | None = None) -> None:
        self._config = config
        self._connector = connector or default_connect
        self._conn: RealtimeConnection | None = None

    async def connect(self) -> None:
        uri = build_realtime_uri(self._config.url, self._config.model)
        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        self._conn = await self._connector(uri, headers)
        await self._send(build_tts_session_update(self._config))

    async def synthesize(self, text: str) -> None:
        """送一段待合成文本并提交（触发合成）。"""
        await self._send(build_text_append(text))
        await self._send(build_text_commit())

    async def finish(self) -> None:
        if self._conn is not None:
            await self._send(build_tts_session_finish())

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def receive(self) -> TtsEvent | None:
        """接收并解析一条服务端事件。音频/结束事件返回 TtsEvent，无关事件返回 None，
        错误事件抛 TtsError，连接关闭抛 TtsConnectionClosed。"""
        conn = self._require_conn()
        try:
            raw = await conn.recv()
        except ConnectionClosed as e:
            raise TtsConnectionClosed("connection_closed", "TTS 连接已关闭") from e
        message = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("TTS 事件 JSON 解析失败，跳过")
            return None
        if not isinstance(event, dict):
            return None
        return parse_tts_server_event(cast(dict[str, Any], event))

    def _require_conn(self) -> RealtimeConnection:
        if self._conn is None:
            raise TtsError("not_connected", "TTS 连接未建立")
        return self._conn

    async def _send(self, payload: dict[str, Any]) -> None:
        conn = self._require_conn()
        await conn.send(json.dumps(payload, ensure_ascii=False))
