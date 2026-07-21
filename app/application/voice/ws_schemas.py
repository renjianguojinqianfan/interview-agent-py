"""语音面试 WebSocket 消息协议 schemas。

客户端 -> 服务端：audio（base64 PCM）、control（连接控制）。
服务端 -> 客户端：subtitle（ASR 字幕）、text（AI 文本）、audio_chunk（TTS 音频）、
warning（#17 暂停超时警告）、error。

#15 仅实际使用 audio -> ASR -> subtitle/error；text/audio_chunk 协议先行定义以稳定契约。
出站消息经 model_dump(by_alias=True) 序列化为 camelCase JSON。
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


class SubtitleMessage(BaseSchema):
    """字幕消息：ASR 识别结果。is_final=False 为实时预览，True 为最终结果。"""

    type: Literal["subtitle"] = "subtitle"
    text: str
    is_final: bool


class TextMessage(BaseSchema):
    """AI 文本消息（#16 语音 LLM 使用）。"""

    type: Literal["text"] = "text"
    text: str
    is_final: bool


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


class WarningMessage(BaseSchema):
    """警告消息（#17）：如暂停超时前的 4:30 提醒；不中断会话。"""

    type: Literal["warning"] = "warning"
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
