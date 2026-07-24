"""会话状态机校验单元测试。"""

import pytest

from app.domain.entities.interview import SessionStatus
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.session_state import is_unfinished, validate_transition


class TestValidateTransition:
    def test_created_to_in_progress(self) -> None:
        validate_transition(SessionStatus.CREATED, SessionStatus.IN_PROGRESS)

    def test_created_to_completed(self) -> None:
        validate_transition(SessionStatus.CREATED, SessionStatus.COMPLETED)

    def test_in_progress_to_completed(self) -> None:
        validate_transition(SessionStatus.IN_PROGRESS, SessionStatus.COMPLETED)

    def test_in_progress_to_in_progress_raises(self) -> None:
        with pytest.raises(BusinessException) as exc_info:
            validate_transition(SessionStatus.IN_PROGRESS, SessionStatus.IN_PROGRESS)
        assert exc_info.value.error_code == ErrorCode.BAD_REQUEST

    def test_completed_to_in_progress_raises(self) -> None:
        with pytest.raises(BusinessException):
            validate_transition(SessionStatus.COMPLETED, SessionStatus.IN_PROGRESS)

    def test_completed_to_completed_raises_already_completed(self) -> None:
        with pytest.raises(BusinessException) as exc_info:
            validate_transition(SessionStatus.COMPLETED, SessionStatus.COMPLETED)
        assert exc_info.value.error_code == ErrorCode.INTERVIEW_ALREADY_COMPLETED

    def test_evaluated_to_anything_raises(self) -> None:
        with pytest.raises(BusinessException):
            validate_transition(SessionStatus.EVALUATED, SessionStatus.IN_PROGRESS)
        with pytest.raises(BusinessException):
            validate_transition(SessionStatus.EVALUATED, SessionStatus.COMPLETED)


class TestIsUnfinished:
    def test_created(self) -> None:
        assert is_unfinished(SessionStatus.CREATED) is True

    def test_in_progress(self) -> None:
        assert is_unfinished(SessionStatus.IN_PROGRESS) is True

    def test_completed(self) -> None:
        assert is_unfinished(SessionStatus.COMPLETED) is False

    def test_evaluated(self) -> None:
        assert is_unfinished(SessionStatus.EVALUATED) is False
