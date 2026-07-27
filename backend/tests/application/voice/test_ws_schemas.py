"""语音面试 WebSocket 消息协议 schemas 测试。"""

import pytest

from app.application.voice.ws_schemas import (
    AudioChunkMessage,
    AudioMessage,
    ControlMessage,
    ErrorMessage,
    ServerControlMessage,
    SubtitleMessage,
    TextMessage,
    parse_client_message,
)


class TestParseClientMessage:
    def test_parses_audio(self) -> None:
        msg = parse_client_message({"type": "audio", "data": "QUJD"})
        assert isinstance(msg, AudioMessage)
        assert msg.data == "QUJD"

    def test_parses_control(self) -> None:
        msg = parse_client_message({"type": "control", "action": "finish"})
        assert isinstance(msg, ControlMessage)
        assert msg.action == "finish"

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="未知的客户端消息类型"):
            parse_client_message({"type": "video"})

    def test_missing_type_raises(self) -> None:
        with pytest.raises(ValueError, match="未知的客户端消息类型"):
            parse_client_message({"data": "QUJD"})


class TestOutboundSerialization:
    def test_subtitle_camel_case(self) -> None:
        dumped = SubtitleMessage(text="你好", is_final=False).model_dump(by_alias=True)
        assert dumped == {"type": "subtitle", "text": "你好", "isFinal": False}

    def test_text_uses_content_and_final_fields(self) -> None:
        """#54：text 消息字段须为 content/final（前端 WebSocketTextMessage 契约）。"""
        dumped = TextMessage(content="回答", final=True).model_dump(by_alias=True)
        assert dumped == {"type": "text", "content": "回答", "final": True}

    def test_server_control_message(self) -> None:
        """#54：服务端出站控制消息（asr_ready/asr_reconnecting/audio_complete/pause_timeout*）。

        message 为空时经 exclude_none 序列化不下发 null 字段（对齐 Java 版线上格式）。
        """
        dumped = ServerControlMessage(action="asr_ready").model_dump(by_alias=True, exclude_none=True)
        assert dumped == {"type": "control", "action": "asr_ready"}
        dumped = ServerControlMessage(action="asr_reconnecting", message="重连中").model_dump(
            by_alias=True, exclude_none=True
        )
        assert dumped == {"type": "control", "action": "asr_reconnecting", "message": "重连中"}

    def test_audio_chunk_camel_case(self) -> None:
        dumped = AudioChunkMessage(index=0, data="QUJD", is_last=True).model_dump(by_alias=True)
        assert dumped == {"type": "audio_chunk", "index": 0, "data": "QUJD", "isLast": True}

    def test_error_message(self) -> None:
        dumped = ErrorMessage(code="asr_error", message="失败").model_dump(by_alias=True)
        assert dumped == {"type": "error", "code": "asr_error", "message": "失败"}
