"""语音面试 WebSocket 消息协议 schemas 测试。"""

import pytest

from app.application.voice.ws_schemas import (
    AudioChunkMessage,
    AudioMessage,
    ControlMessage,
    ErrorMessage,
    SubtitleMessage,
    TextMessage,
    WarningMessage,
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

    def test_text_camel_case(self) -> None:
        dumped = TextMessage(text="回答", is_final=True).model_dump(by_alias=True)
        assert dumped == {"type": "text", "text": "回答", "isFinal": True}

    def test_audio_chunk_camel_case(self) -> None:
        dumped = AudioChunkMessage(index=0, data="QUJD", is_last=True).model_dump(by_alias=True)
        assert dumped == {"type": "audio_chunk", "index": 0, "data": "QUJD", "isLast": True}

    def test_error_message(self) -> None:
        dumped = ErrorMessage(code="asr_error", message="失败").model_dump(by_alias=True)
        assert dumped == {"type": "error", "code": "asr_error", "message": "失败"}

    def test_warning_message(self) -> None:
        dumped = WarningMessage(code="pause_timeout_warning", message="即将暂停").model_dump(by_alias=True)
        assert dumped == {"type": "warning", "code": "pause_timeout_warning", "message": "即将暂停"}
