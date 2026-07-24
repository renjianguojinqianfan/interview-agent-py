from app.infrastructure.voice.realtime_ws import build_realtime_uri, new_event_id


class TestBuildRealtimeUri:
    def test_appends_model_param_without_existing_query(self) -> None:
        assert build_realtime_uri("wss://host/realtime", "qwen3-asr") == "wss://host/realtime?model=qwen3-asr"

    def test_appends_model_param_with_existing_query(self) -> None:
        assert build_realtime_uri("wss://host/realtime?x=1", "qwen3-tts") == "wss://host/realtime?x=1&model=qwen3-tts"


class TestNewEventId:
    def test_starts_with_event_prefix(self) -> None:
        assert new_event_id().startswith("event_")

    def test_unique_per_call(self) -> None:
        assert new_event_id() != new_event_id()
