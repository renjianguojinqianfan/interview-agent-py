"""面试评估消费者测试：mock 仓储/图/LLM，验证双源合并 QaRecord + 持久化 + 状态机。"""

import json
from unittest.mock import AsyncMock, MagicMock

from app.domain.entities.evaluation import (
    CategoryScore,
    EvaluationReport,
    QuestionEvaluation,
    ReferenceAnswer,
)
from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.services.evaluation import build_qa_records, overlay_answers
from app.infrastructure.db.models.interview import InterviewAnswer as InterviewAnswerORM
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM
from app.infrastructure.db.models.resume import Resume
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.constants import INTERVIEW_EVALUATE
from app.infrastructure.tasks.interview_evaluate_consumer import EvaluateStreamConsumer
from app.infrastructure.tasks.interview_evaluate_producer import EvaluatePayload


def _questions_json(n: int = 2) -> str:
    """questions_json 快照：创建时写入，userAnswer 恒为 None（DB 不回写）。"""
    items = [
        {
            "questionIndex": i,
            "question": f"题{i}",
            "type": "JAVA",
            "category": "Java",
            "topicSummary": f"topic{i}",
            "userAnswer": None,
            "score": None,
            "feedback": None,
            "isFollowUp": False,
            "parentQuestionIndex": None,
        }
        for i in range(n)
    ]
    return json.dumps(items, ensure_ascii=False)


def _make_session_orm(**overrides: object) -> InterviewSessionORM:
    defaults: dict[str, object] = {
        "id": 1,
        "session_id": "sess123",
        "skill_id": "java-backend",
        "difficulty": "mid",
        "resume_id": None,
        "total_questions": 2,
        "current_question_index": 2,
        "status": "COMPLETED",
        "questions_json": _questions_json(2),
        "evaluate_status": AsyncTaskStatus.PENDING.value,
        "evaluate_error": None,
    }
    defaults.update(overrides)
    return InterviewSessionORM(**defaults)  # type: ignore[arg-type]


def _make_answer_orm(index: int, answer: str) -> InterviewAnswerORM:
    return InterviewAnswerORM(
        id=index + 1,
        session_id=1,
        question_index=index,
        question=f"题{index}",
        category="Java",
        user_answer=answer,
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
        session_id="sess123",
        total_questions=2,
        overall_score=80,
        category_scores=[CategoryScore(category="Java", score=80, question_count=2)],
        question_details=[
            QuestionEvaluation(0, "题0", "Java", "答0", 90, "优"),
            QuestionEvaluation(1, "题1", "Java", "答1", 70, "良"),
        ],
        overall_feedback="总评",
        strengths=["扎实"],
        improvements=["需补深度"],
        reference_answers=[
            ReferenceAnswer(0, "题0", "参考0", ["要点0"]),
            ReferenceAnswer(1, "题1", "参考1", ["要点1"]),
        ],
    )


def _make_session_factory() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


def _make_consumer(
    session_orm: InterviewSessionORM | None = None,
    answers: list[InterviewAnswerORM] | None = None,
    report: EvaluationReport | None = None,
    resume: Resume | None = None,
) -> tuple[EvaluateStreamConsumer, dict[str, MagicMock]]:
    factory, _ = _make_session_factory()
    repository = MagicMock()
    repository.find_by_session_id = AsyncMock(return_value=session_orm)
    repository.find_answers_by_session_id = AsyncMock(return_value=answers or [])
    repository.update_evaluate_status = AsyncMock()
    repository.save_evaluation_result = AsyncMock()
    repository.update_answer_evaluation = AsyncMock()

    resume_repository = MagicMock()
    resume_repository.get_by_id = AsyncMock(return_value=resume)

    llm_registry = MagicMock()
    llm_registry.get_chat_client = AsyncMock(return_value=MagicMock(name="chat_client"))

    evaluation_graph = MagicMock()
    evaluation_graph.evaluate = AsyncMock(return_value=report or _make_report())

    consumer = EvaluateStreamConsumer(
        redis_client=RedisClient(AsyncMock()),
        config=INTERVIEW_EVALUATE,
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
    def test_parses_session_id(self) -> None:
        consumer, _ = _make_consumer()
        data = {b"sessionId": b"sess123", b"retryCount": b"0"}
        payload = consumer.parse_payload("100-0", data)
        assert payload is not None
        assert payload.session_id == "sess123"

    def test_returns_none_when_session_id_missing(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.parse_payload("100-0", {b"retryCount": b"0"}) is None


class TestShouldSkip:
    def test_always_returns_false(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.should_skip(EvaluatePayload(session_id="sess123")) is False


class TestMarkProcessing:
    async def test_sets_processing_for_pending(self) -> None:
        orm = _make_session_orm(evaluate_status=AsyncTaskStatus.PENDING.value)
        consumer, deps = _make_consumer(session_orm=orm)
        await consumer.mark_processing(EvaluatePayload(session_id="sess123"))
        deps["repository"].update_evaluate_status.assert_awaited_once()
        assert deps["repository"].update_evaluate_status.call_args.args[2] == AsyncTaskStatus.PROCESSING.value

    async def test_skips_completed(self) -> None:
        orm = _make_session_orm(evaluate_status=AsyncTaskStatus.COMPLETED.value)
        consumer, deps = _make_consumer(session_orm=orm)
        await consumer.mark_processing(EvaluatePayload(session_id="sess123"))
        deps["repository"].update_evaluate_status.assert_not_awaited()

    async def test_noop_when_deleted(self) -> None:
        consumer, deps = _make_consumer(session_orm=None)
        await consumer.mark_processing(EvaluatePayload(session_id="sess123"))
        deps["repository"].update_evaluate_status.assert_not_awaited()


class TestProcessBusiness:
    async def test_skips_completed_evaluation(self) -> None:
        orm = _make_session_orm(evaluate_status=AsyncTaskStatus.COMPLETED.value)
        consumer, deps = _make_consumer(session_orm=orm)
        await consumer.process_business(EvaluatePayload(session_id="sess123"))
        deps["evaluation_graph"].evaluate.assert_not_awaited()

    async def test_skips_deleted_session(self) -> None:
        consumer, deps = _make_consumer(session_orm=None)
        await consumer.process_business(EvaluatePayload(session_id="sess123"))
        deps["evaluation_graph"].evaluate.assert_not_awaited()

    async def test_merges_questions_json_with_answers_table(self) -> None:
        # questions_json 的 userAnswer 恒 None；answers 表是权威来源
        orm = _make_session_orm()
        answers = [_make_answer_orm(0, "答0"), _make_answer_orm(1, "答1")]
        consumer, deps = _make_consumer(session_orm=orm, answers=answers)
        await consumer.process_business(EvaluatePayload(session_id="sess123"))

        evaluate_call = deps["evaluation_graph"].evaluate.call_args
        qa_records = evaluate_call.kwargs.get("qa_records") or evaluate_call.args[2]
        # 合并后 user_answer 来自 answers 表而非 questions_json 的 None
        assert qa_records[0].user_answer == "答0"
        assert qa_records[1].user_answer == "答1"
        assert qa_records[0].question == "题0"

    async def test_persists_evaluation_result_and_answer_updates(self) -> None:
        orm = _make_session_orm()
        answers = [_make_answer_orm(0, "答0"), _make_answer_orm(1, "答1")]
        consumer, deps = _make_consumer(session_orm=orm, answers=answers)
        await consumer.process_business(EvaluatePayload(session_id="sess123"))

        deps["repository"].save_evaluation_result.assert_awaited_once()
        save_kwargs = deps["repository"].save_evaluation_result.call_args.kwargs
        assert save_kwargs["report"].overall_score == 80
        assert save_kwargs["report"].overall_feedback == "总评"
        assert "扎实" in save_kwargs["report"].strengths
        # 每题 answer 都被回写
        assert deps["repository"].update_answer_evaluation.await_count == 2

    async def test_loads_resume_text_when_resume_id_present(self) -> None:
        orm = _make_session_orm(resume_id=10)
        resume = _make_resume()
        consumer, deps = _make_consumer(session_orm=orm, resume=resume)
        await consumer.process_business(EvaluatePayload(session_id="sess123"))

        deps["resume_repository"].get_by_id.assert_awaited_once()
        evaluate_call = deps["evaluation_graph"].evaluate.call_args
        resume_text = evaluate_call.kwargs.get("resume_text") or evaluate_call.args[3]
        assert resume_text == "张三 Java 工程师"

    async def test_unanswered_question_stays_none_in_qa_record(self) -> None:
        # 仅回答第 0 题，第 1 题无 answer 记录
        orm = _make_session_orm()
        answers = [_make_answer_orm(0, "答0")]
        consumer, deps = _make_consumer(session_orm=orm, answers=answers)
        await consumer.process_business(EvaluatePayload(session_id="sess123"))

        qa_records = deps["evaluation_graph"].evaluate.call_args.kwargs["qa_records"]
        assert qa_records[0].user_answer == "答0"
        assert qa_records[1].user_answer is None


class TestMarkCompleted:
    async def test_sets_completed(self) -> None:
        orm = _make_session_orm()
        consumer, deps = _make_consumer(session_orm=orm)
        await consumer.mark_completed(EvaluatePayload(session_id="sess123"))
        assert deps["repository"].update_evaluate_status.call_args.args[2] == AsyncTaskStatus.COMPLETED.value

    async def test_noop_when_deleted(self) -> None:
        consumer, deps = _make_consumer(session_orm=None)
        await consumer.mark_completed(EvaluatePayload(session_id="sess123"))
        deps["repository"].update_evaluate_status.assert_not_awaited()


class TestMarkFailed:
    async def test_sets_failed_with_error(self) -> None:
        orm = _make_session_orm()
        consumer, deps = _make_consumer(session_orm=orm)
        await consumer.mark_failed(EvaluatePayload(session_id="sess123"), "LLM 超时")
        args = deps["repository"].update_evaluate_status.call_args.args
        assert args[2] == AsyncTaskStatus.FAILED.value
        assert args[3] == "LLM 超时"


class TestRetryMessage:
    async def test_re_enqueues_with_retry_count(self) -> None:
        consumer, _ = _make_consumer()
        consumer._redis.xadd = AsyncMock(return_value="200-0")
        await consumer.retry_message(EvaluatePayload(session_id="sess123"), 2)
        call_args = consumer._redis.xadd.call_args
        assert call_args.args[0] == "interview:evaluate:stream"
        assert call_args.args[1]["sessionId"] == "sess123"
        assert call_args.args[1]["retryCount"] == "2"


class TestOverlayAnswersIntegration:
    """验证双源合并纯函数与消费者实际数据形态一致。"""

    def test_questions_json_useranswer_none_overlaid_by_answers(self) -> None:
        from app.application.interview.question_codec import deserialize_questions

        questions = deserialize_questions(_questions_json(2))
        # 模拟消费者从 answers 表提取的 answer_map
        answer_map = {0: "答0", 1: "答1"}
        merged = overlay_answers(questions, answer_map)
        records = build_qa_records(merged)
        assert records[0].user_answer == "答0"
        assert records[1].user_answer == "答1"
