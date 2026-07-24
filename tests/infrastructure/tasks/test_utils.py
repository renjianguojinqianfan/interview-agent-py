from app.infrastructure.tasks.utils import truncate_error


class TestTruncateError:
    def test_returns_unchanged_when_below_limit(self) -> None:
        message = "boom"
        assert truncate_error(message) == "boom"

    def test_returns_unchanged_at_exactly_limit(self) -> None:
        message = "x" * 500
        assert truncate_error(message) == message

    def test_cuts_at_max_length_when_over_limit(self) -> None:
        message = "y" * 600
        result = truncate_error(message)
        assert len(result) == 500
        assert result == "y" * 500
