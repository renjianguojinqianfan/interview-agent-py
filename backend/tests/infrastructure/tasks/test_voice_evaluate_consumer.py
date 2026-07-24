"""语音面试评估消费者测试：mock 仓储/图/LLM，验证消息适配 QaRecord + 持久化 + 状态机。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.domain.entities.evaluation import (
    CategoryScore,
    EvaluationReport,
    QuestionEvaluation,
    ReferenceAnswer,
)
from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.models.resume import Resume
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewEvaluation as VoiceInterviewEvaluationORM,
)
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewMessage as VoiceInterviewMessageORM,
)
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewSession as VoiceInterviewSessionORM,
)
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.constants import VOICE_EVALUATE
from app.infrastructure.tasks.voice_evaluate_consumer import VoiceEvaluateStreamConsumer
from app.infrastructure.tasks.voice_evaluate_producer import VoiceEvaluatePayload

_NOW = datetime(2026, 7, 21, 10, 0, 0)


def _make_session_orm(**overrides: object) -> VoiceInterviewSessionORM:
    defaults: dict[str, object] = {
        "id": 1,
        "user_id": "default",
        "role_type": "Java面试官",
        "skill_id": "java-backend",
        "difficulty": "mid",
        "current_phase": "COMPLETED",
        "status": "COMPLETED",
        "planned_duration": 30,
        "start_time": _NOW,
        "evaluate_status": AsyncTaskStatus.PENDING.value,
        "evaluate_error": None,
        "resume_id": None,
        "llm_provider": None,
    }
    defaults.update(overrides)
    return VoiceInterviewSessionORM(**defaults)  # type: ignore[arg-type]


def _make_message_orm(seq: int, phase: str, ai_text: str | None, user_text: str | None) -> VoiceInterviewMessageORM:
    return VoiceInterviewMessageORM(
        id=seq,
        session_id=1,
        message_type="DIALOGUE",
        phase=phase,
        ai_generated_text=ai_text,
        user_recognized_text=user_text,
        sequence_num=seq,
    )


def _make_resume() -> Resume:
    return Resume(
        id=10,
        file_hash="h",
        original_filename="r.pdf",
        resume_text="张三 Java 工程师",
        analyze_status="COMPLETED",
    )


def _make_report() -> EvaluationReport:
    return EvaluationReport(
        session_id="1",
        total_questions=2,
        overall_score=80,
        category_scores=[CategoryScore(category="TECH", score=80, question_count=2)],
        question_details=[
            QuestionEvaluation(1, "Q1", "TECH", "A1", 90, "优"),
            QuestionEvaluation(2, "Q2", "TECH", "A2", 70, "良"),
        ],
        overall_feedback="总评",
        strengths=["扎实"],
        improvements=["需补深度"],
        reference_answers=[
            ReferenceAnswer(1, "Q1", "参考1", ["要点1"]),
            ReferenceAnswer(2, "Q2", "参考2", ["要点2"]),
        ],
    )


def _make_session_factory() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


def _make_consumer(
    session_orm: VoiceInterviewSessionORM | None = None,
    messages: list[VoiceInterviewMessageORM] | None = None,
    existing_eval: VoiceInterviewEvaluationORM | None = None,
    report: EvaluationReport | None = None,
    resume: Resume | None = None,
) -> tuple[VoiceEvaluateStreamConsumer, dict[str, MagicMock]]:
    factory, _ = _make_session_factory()
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=session_orm)
    repository.find_messages_by_session = AsyncMock(return_value=messages or [])
    repository.update_evaluate_status = AsyncMock()
    repository.get_evaluation_by_session = AsyncMock(return_value=existing_eval)
    repository.save_evaluation = AsyncMock()

    resume_repository = MagicMock()
    resume_repository.get_by_id = AsyncMock(return_value=resume)

    llm_registry = MagicMock()
    llm_registry.get_chat_client = AsyncMock(return_value=MagicMock(name="chat_client"))
    llm_registry.resolve_provider_id_by_name = AsyncMock(return_value=None)

    evaluation_graph = MagicMock()
    evaluation_graph.evaluate = AsyncMock(return_value=report or _make_report())

    consumer = VoiceEvaluateStreamConsumer(
        redis_client=RedisClient(AsyncMock()),
        config=VOICE_EVALUATE,
        session_factory=factory,
        repository=repository,
        resume_repository=resume_repository,
        llm_registry=llm_registry,
        evaluation_graph=evaluation_graph,
    )
    return consumer, {
        "repository": repository,
        "resume_repository": resume_repository,
        "llm_registry": llm_registry,
        "evaluation_graph": evaluation_graph,
    }


class TestParsePayload:
    def test_parses_int_session_id(self) -> None:
        consumer, _ = _make_consumer()
        data = {b"sessionId": b"1", b"retryCount": b"0"}
        payload = consumer.parse_payload("100-0", data)
        assert payload is not None
        assert payload.session_id == 1

    def test_returns_none_when_session_id_missing(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.parse_payload("100-0", {b"retryCount": b"0"}) is None

    def test_returns_none_for_non_numeric(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.parse_payload("100-0", {b"sessionId": b"abc"}) is None


class TestShouldSkip:
    def test_always_returns_false(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.should_skip(VoiceEvaluatePayload(session_id=1)) is False


class TestMarkProcessing:
    async def test_sets_processing_for_pending(self) -> None:
        orm = _make_session_orm(evaluate_status=AsyncTaskStatus.PENDING.value)
        consumer, deps = _make_consumer(session_orm=orm)
        await consumer.mark_processing(VoiceEvaluatePayload(session_id=1))
        deps["repository"].update_evaluate_status.assert_awaited_once()
        assert deps["repository"].update_evaluate_status.call_args.args[2] == AsyncTaskStatus.PROCESSING.value

    async def test_skips_completed(self) -> None:
        orm = _make_session_orm(evaluate_status=AsyncTaskStatus.COMPLETED.value)
        consumer, deps = _make_consumer(session_orm=orm)
        await consumer.mark_processing(VoiceEvaluatePayload(session_id=1))
        deps["repository"].update_evaluate_status.assert_not_awaited()

    async def test_noop_when_deleted(self) -> None:
        consumer, deps = _make_consumer(session_orm=None)
        await consumer.mark_processing(VoiceEvaluatePayload(session_id=1))
        deps["repository"].update_evaluate_status.assert_not_awaited()


class TestProcessBusiness:
    async def test_skips_completed_evaluation(self) -> None:
        orm = _make_session_orm(evaluate_status=AsyncTaskStatus.COMPLETED.value)
        consumer, deps = _make_consumer(session_orm=orm)
        await consumer.process_business(VoiceEvaluatePayload(session_id=1))
        deps["evaluation_graph"].evaluate.assert_not_awaited()

    async def test_skips_deleted_session(self) -> None:
        consumer, deps = _make_consumer(session_orm=None)
        await consumer.process_business(VoiceEvaluatePayload(session_id=1))
        deps["evaluation_graph"].evaluate.assert_not_awaited()

    async def test_adapts_messages_to_qa_records_with_phase_category(self) -> None:
        orm = _make_session_orm()
        messages = [
            _make_message_orm(1, "TECH", "Q1", "A1"),
            _make_message_orm(2, "HR", "Q2", "A2"),
        ]
        consumer, deps = _make_consumer(session_orm=orm, messages=messages)
        await consumer.process_business(VoiceEvaluatePayload(session_id=1))

        qa_records = deps["evaluation_graph"].evaluate.call_args.kwargs["qa_records"]
        assert qa_records[0].question == "Q1"
        assert qa_records[0].category == "TECH"
        assert qa_records[0].user_answer == "A1"
        assert qa_records[1].category == "HR"

    async def test_unanswered_message_yields_none_answer(self) -> None:
        orm = _make_session_orm()
        messages = [_make_message_orm(1, "TECH", "Q1", None)]
        consumer, deps = _make_consumer(session_orm=orm, messages=messages)
        await consumer.process_business(VoiceEvaluatePayload(session_id=1))

        qa_records = deps["evaluation_graph"].evaluate.call_args.kwargs["qa_records"]
        assert qa_records[0].user_answer is None

    async def test_skips_message_without_ai_question(self) -> None:
        orm = _make_session_orm()
        messages = [_make_message_orm(1, "TECH", None, "用户独白")]
        consumer, deps = _make_consumer(session_orm=orm, messages=messages)
        await consumer.process_business(VoiceEvaluatePayload(session_id=1))

        qa_records = deps["evaluation_graph"].evaluate.call_args.kwargs["qa_records"]
        assert qa_records == []

    async def test_persists_new_evaluation_row(self) -> None:
        orm = _make_session_orm()
        messages = [_make_message_orm(1, "TECH", "Q1", "A1")]
        consumer, deps = _make_consumer(session_orm=orm, messages=messages, existing_eval=None)
        await consumer.process_business(VoiceEvaluatePayload(session_id=1))

        deps["repository"].save_evaluation.assert_awaited_once()
        saved: VoiceInterviewEvaluationORM = deps["repository"].save_evaluation.call_args.args[1]
        assert saved.session_id == 1
        assert saved.overall_score == 80
        assert saved.interviewer_role == "Java面试官"
        assert saved.interview_date == _NOW

    async def test_updates_existing_evaluation_row(self) -> None:
        orm = _make_session_orm()
        existing = VoiceInterviewEvaluationORM(id=5, session_id=1, overall_score=0, overall_feedback="")
        messages = [_make_message_orm(1, "TECH", "Q1", "A1")]
        consumer, deps = _make_consumer(session_orm=orm, messages=messages, existing_eval=existing)
        await consumer.process_business(VoiceEvaluatePayload(session_id=1))

        deps["repository"].save_evaluation.assert_not_awaited()
        assert existing.overall_score == 80
        assert existing.overall_feedback == "总评"

    async def test_loads_resume_text_when_resume_id_present(self) -> None:
        orm = _make_session_orm(resume_id=10)
        resume = _make_resume()
        messages = [_make_message_orm(1, "TECH", "Q1", "A1")]
        consumer, deps = _make_consumer(session_orm=orm, messages=messages, resume=resume)
        await consumer.process_business(VoiceEvaluatePayload(session_id=1))

        deps["resume_repository"].get_by_id.assert_awaited_once()
        resume_text = deps["evaluation_graph"].evaluate.call_args.kwargs["resume_text"]
        assert resume_text == "张三 Java 工程师"


class TestMarkCompleted:
    async def test_sets_completed(self) -> None:
        orm = _make_session_orm()
        consumer, deps = _make_consumer(session_orm=orm)
        await consumer.mark_completed(VoiceEvaluatePayload(session_id=1))
        assert deps["repository"].update_evaluate_status.call_args.args[2] == AsyncTaskStatus.COMPLETED.value

    async def test_noop_when_deleted(self) -> None:
        consumer, deps = _make_consumer(session_orm=None)
        await consumer.mark_completed(VoiceEvaluatePayload(session_id=1))
        deps["repository"].update_evaluate_status.assert_not_awaited()


class TestMarkFailed:
    async def test_sets_failed_with_error(self) -> None:
        orm = _make_session_orm()
        consumer, deps = _make_consumer(session_orm=orm)
        await consumer.mark_failed(VoiceEvaluatePayload(session_id=1), "LLM 超时")
        args = deps["repository"].update_evaluate_status.call_args.args
        assert args[2] == AsyncTaskStatus.FAILED.value
        assert args[3] == "LLM 超时"


class TestRetryMessage:
    async def test_re_enqueues_with_retry_count(self) -> None:
        consumer, _ = _make_consumer()
        consumer._redis.xadd = AsyncMock(return_value="200-0")
        await consumer.retry_message(VoiceEvaluatePayload(session_id=1), 2)
        call_args = consumer._redis.xadd.call_args
        assert call_args.args[0] == "voice:evaluate:stream"
        assert call_args.args[1]["sessionId"] == "1"
        assert call_args.args[1]["retryCount"] == "2"
