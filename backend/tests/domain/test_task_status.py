from app.domain.entities.task_status import AsyncTaskStatus


class TestAsyncTaskStatus:
    def test_has_four_lifecycle_states(self) -> None:
        assert AsyncTaskStatus.PENDING != AsyncTaskStatus.PROCESSING
        assert AsyncTaskStatus.PROCESSING != AsyncTaskStatus.COMPLETED
        assert AsyncTaskStatus.COMPLETED != AsyncTaskStatus.FAILED

    def test_pending_is_initial_state_for_new_resume(self) -> None:
        assert AsyncTaskStatus.PENDING.value == "PENDING"

    def test_all_states_have_string_values(self) -> None:
        for status in AsyncTaskStatus:
            assert isinstance(status.value, str)
            assert status.name == status.value
