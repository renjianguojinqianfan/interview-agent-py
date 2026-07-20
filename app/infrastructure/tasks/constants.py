from dataclasses import dataclass

FIELD_RETRY_COUNT = "retryCount"
FIELD_CONTENT = "content"

MAX_RETRY_COUNT = 3
BATCH_SIZE = 10
EMBEDDING_BATCH_SIZE = 10
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

INTERVIEW_EVALUATE = StreamConfig(
    # Used by issue #8 (interview async evaluation producer; consumer in #9)
    stream_key="interview:evaluate:stream",
    group_name="evaluate-group",
    consumer_prefix="evaluate-consumer-",
    id_field="sessionId",
)

KB_VECTORIZE = StreamConfig(
    # Used by issue #10 (knowledge base async vectorization)
    stream_key="knowledgebase:vectorize:stream",
    group_name="vectorize-group",
    consumer_prefix="vectorize-consumer-",
    id_field="knowledgeBaseId",
)
