from unittest.mock import AsyncMock, MagicMock

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.tasks.base_evaluate_consumer import BaseEvaluateStreamConsumer
from app.infrastructure.tasks.constants import INTERVIEW_EVALUATE

_ORM = object()


class _SessionCtx:
    def __init__(self, session: MagicMock) -> None:
        self._session = session

    async def __aenter__(self) -> MagicMock:
        return self._session

    async def __aexit__(self, *args: object) -> bool:
        return False


class FakeConsumer(BaseEvaluateStreamConsumer[str, object]):
    """测试用具体子类：抽象钩子返回注入值并记录状态更新/持久化调用。"""

    def __init__(
        self,
        redis_client: MagicMock,
        config: object,
        session_factory: MagicMock,
        resume_repository: MagicMock,
        llm_registry: MagicMock,
        evaluation_graph: MagicMock,
        *,
        orm: object | None,
        status: str | None,
        resume_id: int | None,
        provider: str | None,
        qa_records: list[object] | None,
    ) -> None:
        super().__init__(
            redis_client,  # type: ignore[arg-type]
            config,  # type: ignore[arg-type]
            session_factory,
            resume_repository,  # type: ignore[arg-type]
            llm_registry,  # type: ignore[arg-type]
            evaluation_graph,  # type: ignore[arg-type]
        )
        self._orm = orm
        self._status = status
        self._resume_id_val = resume_id
        self._provider_val = provider
        self._qa_records = qa_records or []
        self.update_calls: list[tuple[str, str | None]] = []
        self.persist_calls: list[object] = []

    def task_display_name(self) -> str:
        return "Fake"

    def parse_payload(self, msg_id: str, data: dict[bytes, bytes]) -> str | None:
        return None

    def _session_id_text(self, payload: str) -> str:
        return payload

    async def _get_session_orm(self, session: object, payload: str) -> object | None:
        return self._orm

    def _evaluate_status(self, orm: object) -> str | None:
        return self._status

    def _resume_id(self, orm: object) -> int | None:
        return self._resume_id_val

    def _llm_provider(self, orm: object) -> str | None:
        return self._provider_val

    async def _update_evaluate_status(self, session: object, orm: object, status: str, error: str | None) -> None:
        self.update_calls.append((status, error))

    async def _build_qa_records(self, session: object, orm: object) -> list[object]:  # type: ignore[override]
        return self._qa_records

    async def _persist_result(self, session: object, orm: object, report: object) -> None:
        self.persist_calls.append(report)


def _make_session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    return session


def _make_consumer(
    *,
    orm: object | None = _ORM,
    status: str | None = "PENDING",
    resume_id: int | None = None,
    provider: str | None = None,
    qa_records: list[object] | None = None,
) -> tuple[FakeConsumer, MagicMock]:
    session = _make_session()
    resume_repo = MagicMock()
    resume_repo.get_by_id = AsyncMock()
    llm_registry = MagicMock()
    llm_registry.resolve_provider_id_by_name = AsyncMock(return_value=None)
    llm_registry.get_chat_client = AsyncMock()
    graph = MagicMock()
    graph.evaluate = AsyncMock()
    factory = MagicMock(return_value=_SessionCtx(session))
    consumer = FakeConsumer(
        AsyncMock(),
        INTERVIEW_EVALUATE,
        factory,
        resume_repo,
        llm_registry,
        graph,
        orm=orm,
        status=status,
        resume_id=resume_id,
        provider=provider,
        qa_records=qa_records,
    )
    return consumer, session


class TestMarkProcessing:
    async def test_skips_when_completed(self) -> None:
        consumer, session = _make_consumer(status="COMPLETED")
        await consumer.mark_processing("sess1")
        assert consumer.update_calls == []
        session.commit.assert_not_awaited()

    async def test_skips_when_session_deleted(self) -> None:
        consumer, session = _make_consumer(orm=None)
        await consumer.mark_processing("sess1")
        assert consumer.update_calls == []
        session.commit.assert_not_awaited()

    async def test_sets_processing_when_pending(self) -> None:
        consumer, session = _make_consumer(status="PENDING")
        await consumer.mark_processing("sess1")
        assert consumer.update_calls == [("PROCESSING", None)]
        session.commit.assert_awaited_once()


class TestProcessBusiness:
    async def test_skips_when_session_deleted(self) -> None:
        consumer, session = _make_consumer(orm=None)
        await consumer.process_business("sess1")
        consumer._evaluation_graph.evaluate.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_skips_when_completed(self) -> None:
        consumer, session = _make_consumer(status="COMPLETED")
        await consumer.process_business("sess1")
        consumer._evaluation_graph.evaluate.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_runs_evaluation_and_persists(self) -> None:
        qa = MagicMock()
        consumer, session = _make_consumer(status="PENDING", resume_id=42, provider="dashscope", qa_records=[qa])
        consumer._resume_repository.get_by_id = AsyncMock(return_value=MagicMock(resume_text="RT"))
        consumer._llm_registry.resolve_provider_id_by_name = AsyncMock(return_value=7)
        chat_client = object()
        consumer._llm_registry.get_chat_client = AsyncMock(return_value=chat_client)
        report = MagicMock(overall_score=88)
        consumer._evaluation_graph.evaluate = AsyncMock(return_value=report)

        await consumer.process_business("sess1")

        consumer._llm_registry.get_chat_client.assert_awaited_once_with(7)
        consumer._evaluation_graph.evaluate.assert_awaited_once_with(
            chat_client=chat_client, session_id="sess1", qa_records=[qa], resume_text="RT"
        )
        assert consumer.persist_calls == [report]
        session.commit.assert_awaited_once()


class TestResolveProviderId:
    async def test_falls_back_to_none_on_business_exception(self) -> None:
        consumer, _ = _make_consumer()
        consumer._llm_registry.resolve_provider_id_by_name = AsyncMock(
            side_effect=BusinessException(ErrorCode.PROVIDER_NOT_FOUND)
        )
        assert await consumer._resolve_provider_id("bad") is None

    async def test_returns_resolved_id(self) -> None:
        consumer, _ = _make_consumer()
        consumer._llm_registry.resolve_provider_id_by_name = AsyncMock(return_value=9)
        assert await consumer._resolve_provider_id("dashscope") == 9


class TestMarkFailed:
    async def test_updates_status_and_commits(self) -> None:
        consumer, session = _make_consumer()
        await consumer.mark_failed("sess1", "boom")
        assert consumer.update_calls == [("FAILED", "boom")]
        session.commit.assert_awaited_once()

    async def test_skips_when_session_deleted(self) -> None:
        consumer, session = _make_consumer(orm=None)
        await consumer.mark_failed("sess1", "boom")
        assert consumer.update_calls == []
        session.commit.assert_not_awaited()


class TestMarkCompleted:
    async def test_updates_status_and_commits(self) -> None:
        consumer, session = _make_consumer()
        await consumer.mark_completed("sess1")
        assert consumer.update_calls == [("COMPLETED", None)]
        session.commit.assert_awaited_once()
