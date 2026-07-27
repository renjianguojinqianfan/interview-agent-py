"""语音面试 WebSocket 消息协议 schemas。

客户端 -> 服务端：audio（base64 PCM）、control（连接控制）。
服务端 -> 客户端：subtitle（ASR 字幕）、text（AI 文本，字段 content/final）、audio_chunk（TTS 音频）、
control（#54：asr_ready / asr_reconnecting / audio_complete / pause_timeout_warning / pause_timeout）、error。

#15 仅实际使用 audio -> ASR -> subtitle/error；text/audio_chunk 协议先行定义以稳定契约。
#54 服务端出站 control 与 text 字段名以前端（Java 版契约）为准（ADR-0015）；
原 warning 类型前端无处理分支，暂停超时事件并入 control。
出站消息经 model_dump(by_alias=True, exclude_none=True) 序列化为 camelCase JSON。
"""

from typing import Any, Literal

from app.api.responses import BaseSchema


class AudioMessage(BaseSchema):
    """客户端音频帧：data 为 base64 编码的 PCM。"""

    type: Literal["audio"] = "audio"
    data: str


class ControlMessage(BaseSchema):
    """客户端控制消息：action 如 start/stop/finish。"""

    type: Literal["control"] = "control"
    action: str


class ServerControlMessage(BaseSchema):
    """服务端→客户端控制消息（#54）：asr_ready（解锁麦克风）/ asr_reconnecting / audio_complete。"""

    type: Literal["control"] = "control"
    action: str
    message: str | None = None


class SubtitleMessage(BaseSchema):
    """字幕消息：ASR 识别结果。is_final=False 为实时预览，True 为最终结果。"""

    type: Literal["subtitle"] = "subtitle"
    text: str
    is_final: bool


class TextMessage(BaseSchema):
    """AI 文本消息（#16 语音 LLM 使用）。

    #54：字段名以前端契约为准（content/final，非 text/isFinal）；流式发送须为累积全文
    （前端 onTextResponse 直接 setAiText 不做拼接）。
    """

    type: Literal["text"] = "text"
    content: str
    final: bool


class AudioChunkMessage(BaseSchema):
    """AI 语音音频块消息（#16/#17 TTS 使用）。"""

    type: Literal["audio_chunk"] = "audio_chunk"
    index: int
    data: str
    is_last: bool


class ErrorMessage(BaseSchema):
    """错误消息。"""

    type: Literal["error"] = "error"
    code: str
    message: str


type ClientMessage = AudioMessage | ControlMessage


def parse_client_message(raw: dict[str, Any]) -> ClientMessage:
    """按 type 分发解析客户端消息；未知类型抛 ValueError。"""
    msg_type = raw.get("type")
    if msg_type == "audio":
        return AudioMessage.model_validate(raw)
    if msg_type == "control":
        return ControlMessage.model_validate(raw)
    raise ValueError(f"未知的客户端消息类型: {msg_type}")
