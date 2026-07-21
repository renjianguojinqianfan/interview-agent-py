"""语音面试会话状态机校验单元测试。"""

import pytest

from app.domain.entities.voice_interview import VoiceSessionStatus
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.voice_session_state import is_unfinished, validate_transition


class TestValidateTransition:
    def test_in_progress_to_paused(self) -> None:
        validate_transition(VoiceSessionStatus.IN_PROGRESS, VoiceSessionStatus.PAUSED)

    def test_paused_to_in_progress(self) -> None:
        validate_transition(VoiceSessionStatus.PAUSED, VoiceSessionStatus.IN_PROGRESS)

    def test_in_progress_to_completed(self) -> None:
        validate_transition(VoiceSessionStatus.IN_PROGRESS, VoiceSessionStatus.COMPLETED)

    def test_paused_to_completed(self) -> None:
        validate_transition(VoiceSessionStatus.PAUSED, VoiceSessionStatus.COMPLETED)

    def test_in_progress_to_failed(self) -> None:
        validate_transition(VoiceSessionStatus.IN_PROGRESS, VoiceSessionStatus.FAILED)

    def test_paused_to_failed(self) -> None:
        validate_transition(VoiceSessionStatus.PAUSED, VoiceSessionStatus.FAILED)

    def test_in_progress_to_in_progress_raises(self) -> None:
        with pytest.raises(BusinessException) as exc_info:
            validate_transition(VoiceSessionStatus.IN_PROGRESS, VoiceSessionStatus.IN_PROGRESS)
        assert exc_info.value.error_code == ErrorCode.BAD_REQUEST

    def test_paused_to_paused_raises(self) -> None:
        with pytest.raises(BusinessException) as exc_info:
            validate_transition(VoiceSessionStatus.PAUSED, VoiceSessionStatus.PAUSED)
        assert exc_info.value.error_code == ErrorCode.BAD_REQUEST

    def test_completed_to_anything_raises(self) -> None:
        with pytest.raises(BusinessException):
            validate_transition(VoiceSessionStatus.COMPLETED, VoiceSessionStatus.IN_PROGRESS)
        with pytest.raises(BusinessException):
            validate_transition(VoiceSessionStatus.COMPLETED, VoiceSessionStatus.PAUSED)

    def test_completed_to_completed_raises(self) -> None:
        with pytest.raises(BusinessException) as exc_info:
            validate_transition(VoiceSessionStatus.COMPLETED, VoiceSessionStatus.COMPLETED)
        assert exc_info.value.error_code == ErrorCode.BAD_REQUEST

    def test_failed_to_anything_raises(self) -> None:
        with pytest.raises(BusinessException):
            validate_transition(VoiceSessionStatus.FAILED, VoiceSessionStatus.IN_PROGRESS)
        with pytest.raises(BusinessException):
            validate_transition(VoiceSessionStatus.FAILED, VoiceSessionStatus.COMPLETED)


class TestIsUnfinished:
    def test_in_progress(self) -> None:
        assert is_unfinished(VoiceSessionStatus.IN_PROGRESS) is True

    def test_paused(self) -> None:
        assert is_unfinished(VoiceSessionStatus.PAUSED) is True

    def test_completed(self) -> None:
        assert is_unfinished(VoiceSessionStatus.COMPLETED) is False

    def test_failed(self) -> None:
        assert is_unfinished(VoiceSessionStatus.FAILED) is False
