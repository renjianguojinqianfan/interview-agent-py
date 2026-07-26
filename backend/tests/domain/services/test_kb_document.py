"""知识库文档聚合规则单测（ADR-0018，issue #52）。"""

from app.domain.services.kb_document import aggregate_vector_status


class TestAggregateVectorStatus:
    def test_empty_documents_is_pending(self) -> None:
        assert aggregate_vector_status([]) == "PENDING"

    def test_all_completed_is_completed(self) -> None:
        assert aggregate_vector_status(["COMPLETED", "COMPLETED"]) == "COMPLETED"

    def test_any_failed_wins(self) -> None:
        assert aggregate_vector_status(["COMPLETED", "FAILED", "PROCESSING"]) == "FAILED"

    def test_in_flight_documents_mean_processing(self) -> None:
        assert aggregate_vector_status(["COMPLETED", "PENDING"]) == "PROCESSING"
        assert aggregate_vector_status(["PROCESSING"]) == "PROCESSING"

    def test_single_completed(self) -> None:
        assert aggregate_vector_status(["COMPLETED"]) == "COMPLETED"
