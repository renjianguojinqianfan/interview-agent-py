import json
from unittest.mock import AsyncMock, MagicMock

from app.application.resume.grading import ResumeAnalysisResult, ScoreDetail, Suggestion
from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.models.resume import Resume
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.constants import RESUME_ANALYZE
from app.infrastructure.tasks.resume_analyze_consumer import AnalyzeStreamConsumer, ResumeAnalyzePayload


def _make_resume(**overrides: object) -> Resume:
    defaults: dict[str, object] = {
        "id": 1,
        "file_hash": "h",
        "original_filename": "x.pdf",
        "resume_text": "张三 Java 工程师",
        "analyze_status": AsyncTaskStatus.PENDING.value,
        "analyze_error": None,
    }
    defaults.update(overrides)
    return Resume(**defaults)


def _make_grading_result() -> ResumeAnalysisResult:
    return ResumeAnalysisResult(
        overallScore=85,
        scoreDetail=ScoreDetail(
            projectScore=35, skillMatchScore=18, contentScore=13, structureScore=12, expressionScore=7
        ),
        summary="优秀简历",
        strengths=["项目经验丰富"],
        suggestions=[Suggestion(category="项目", priority="高", issue="描述笼统", recommendation="加量化")],
    )


def _make_session_factory() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


def _make_consumer() -> tuple[AnalyzeStreamConsumer, dict[str, MagicMock]]:
    factory, _session = _make_session_factory()
    repository = MagicMock()
    repository.get_by_id = AsyncMock()
    repository.update_analyze_status = AsyncMock()
    repository.save_analysis = AsyncMock()
    repository.delete_analyses_by_resume_id = AsyncMock(return_value=0)
    grading = MagicMock()
    grading.analyze_resume = AsyncMock(return_value=_make_grading_result())
    redis_client = RedisClient(AsyncMock())
    consumer = AnalyzeStreamConsumer(
        redis_client=redis_client,
        config=RESUME_ANALYZE,
        session_factory=factory,
        repository=repository,
        grading_service=grading,
    )
    return consumer, {"repository": repository, "grading": grading}


class TestParsePayload:
    def test_parses_resume_id(self) -> None:
        consumer, _ = _make_consumer()
        data = {b"resumeId": b"42", b"retryCount": b"0"}

        payload = consumer.parse_payload("100-0", data)

        assert payload is not None
        assert payload.resume_id == 42

    def test_returns_none_when_resume_id_missing(self) -> None:
        consumer, _ = _make_consumer()
        data = {b"retryCount": b"0"}

        assert consumer.parse_payload("100-0", data) is None


class TestShouldSkip:
    def test_always_returns_false(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.should_skip(ResumeAnalyzePayload(resume_id=1)) is False


class TestMarkProcessing:
    async def test_sets_processing_for_pending_resume(self) -> None:
        consumer, deps = _make_consumer()
        resume = _make_resume(analyze_status=AsyncTaskStatus.PENDING.value)
        deps["repository"].get_by_id.return_value = resume

        await consumer.mark_processing(ResumeAnalyzePayload(resume_id=1))

        deps["repository"].update_analyze_status.assert_awaited_once()
        assert deps["repository"].update_analyze_status.call_args.args[2] == AsyncTaskStatus.PROCESSING.value

    async def test_does_not_change_completed_resume(self) -> None:
        consumer, deps = _make_consumer()
        resume = _make_resume(analyze_status=AsyncTaskStatus.COMPLETED.value)
        deps["repository"].get_by_id.return_value = resume

        await consumer.mark_processing(ResumeAnalyzePayload(resume_id=1))

        deps["repository"].update_analyze_status.assert_not_awaited()

    async def test_noop_when_resume_deleted(self) -> None:
        consumer, deps = _make_consumer()
        deps["repository"].get_by_id.return_value = None

        await consumer.mark_processing(ResumeAnalyzePayload(resume_id=1))

        deps["repository"].update_analyze_status.assert_not_awaited()


class TestProcessBusiness:
    async def test_grades_and_saves_analysis_for_pending_resume(self) -> None:
        consumer, deps = _make_consumer()
        resume = _make_resume(resume_text="张三简历文本")
        deps["repository"].get_by_id.return_value = resume

        await consumer.process_business(ResumeAnalyzePayload(resume_id=1))

        deps["grading"].analyze_resume.assert_awaited_once_with("张三简历文本")
        deps["repository"].save_analysis.assert_awaited_once()
        saved = deps["repository"].save_analysis.call_args.args[1]
        assert saved.resume_id == 1
        assert saved.overall_score == 85
        assert saved.project_score == 35
        assert saved.summary == "优秀简历"
        assert json.loads(saved.strengths_json) == ["项目经验丰富"]
        suggestions = json.loads(saved.suggestions_json)
        assert suggestions[0]["category"] == "项目"

    async def test_skips_completed_resume(self) -> None:
        consumer, deps = _make_consumer()
        resume = _make_resume(analyze_status=AsyncTaskStatus.COMPLETED.value)
        deps["repository"].get_by_id.return_value = resume

        await consumer.process_business(ResumeAnalyzePayload(resume_id=1))

        deps["grading"].analyze_resume.assert_not_awaited()
        deps["repository"].save_analysis.assert_not_awaited()

    async def test_skips_deleted_resume(self) -> None:
        consumer, deps = _make_consumer()
        deps["repository"].get_by_id.return_value = None

        await consumer.process_business(ResumeAnalyzePayload(resume_id=1))

        deps["grading"].analyze_resume.assert_not_awaited()
        deps["repository"].save_analysis.assert_not_awaited()

    async def test_deletes_old_analyses_before_saving_new_one(self) -> None:
        consumer, deps = _make_consumer()
        resume = _make_resume(resume_text="text")
        deps["repository"].get_by_id.return_value = resume

        await consumer.process_business(ResumeAnalyzePayload(resume_id=1))

        deps["repository"].delete_analyses_by_resume_id.assert_awaited_once_with(
            deps["repository"].get_by_id.call_args.args[0], 1
        )


class TestMarkCompleted:
    async def test_sets_completed_when_resume_exists(self) -> None:
        consumer, deps = _make_consumer()
        deps["repository"].get_by_id.return_value = _make_resume()

        await consumer.mark_completed(ResumeAnalyzePayload(resume_id=1))

        assert deps["repository"].update_analyze_status.call_args.args[2] == AsyncTaskStatus.COMPLETED.value

    async def test_noop_when_resume_deleted(self) -> None:
        consumer, deps = _make_consumer()
        deps["repository"].get_by_id.return_value = None

        await consumer.mark_completed(ResumeAnalyzePayload(resume_id=1))

        deps["repository"].update_analyze_status.assert_not_awaited()


class TestMarkFailed:
    async def test_sets_failed_with_error(self) -> None:
        consumer, deps = _make_consumer()
        deps["repository"].get_by_id.return_value = _make_resume()

        await consumer.mark_failed(ResumeAnalyzePayload(resume_id=1), "LLM 超时")

        args = deps["repository"].update_analyze_status.call_args.args
        assert args[2] == AsyncTaskStatus.FAILED.value
        assert args[3] == "LLM 超时"

    async def test_noop_when_resume_deleted(self) -> None:
        consumer, deps = _make_consumer()
        deps["repository"].get_by_id.return_value = None

        await consumer.mark_failed(ResumeAnalyzePayload(resume_id=1), "err")

        deps["repository"].update_analyze_status.assert_not_awaited()


class TestRetryMessage:
    async def test_re_enqueues_with_retry_count(self) -> None:
        consumer, _ = _make_consumer()
        consumer._redis.xadd = AsyncMock(return_value="200-0")

        await consumer.retry_message(ResumeAnalyzePayload(resume_id=5), 2)

        consumer._redis.xadd.assert_awaited_once()
        call_args = consumer._redis.xadd.call_args
        assert call_args.args[0] == "resume:analyze:stream"
        fields = call_args.args[1]
        assert fields["resumeId"] == "5"
        assert fields["retryCount"] == "2"
