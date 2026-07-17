from dataclasses import dataclass

FIELD_RETRY_COUNT = "retryCount"
FIELD_CONTENT = "content"

MAX_RETRY_COUNT = 3
BATCH_SIZE = 10
PENDING_IDLE_TIMEOUT_MS = 5 * 60 * 1000
PENDING_CLAIM_BATCH_SIZE = 10
POLL_INTERVAL_MS = 1000
STREAM_MAX_LEN = 1000


@dataclass(frozen=True)
class StreamConfig:
    stream_key: str
    group_name: str
    consumer_prefix: str
    id_field: str


RESUME_ANALYZE = StreamConfig(
    # Used by issue #5 (resume async analysis)
    stream_key="resume:analyze:stream",
    group_name="analyze-group",
    consumer_prefix="analyze-consumer-",
    id_field="resumeId",
)
