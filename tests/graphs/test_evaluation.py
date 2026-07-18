"""统一评估 LangGraph 子图测试：mock LLM 调用器，验证分批+并发+两级降级+汇总。"""

from unittest.mock import AsyncMock, MagicMock

from app.domain.entities.evaluation import EvaluationReport, QaRecord
from app.domain.errors import BusinessException
from app.graphs.evaluation import (
    BatchEvaluationOutput,
    EvaluationGraph,
    QuestionEvaluationOutput,
    SummaryEvaluationOutput,
)


def _qa(index: int, answer: str | None = "答") -> QaRecord:
    return QaRecord(question_index=index, question=f"题{index}", category="JAVA", user_answer=answer)


def _eval_output(index: int, score: int = 80, feedback: str = "好") -> QuestionEvaluationOutput:
    return QuestionEvaluationOutput(
        questionIndex=index, score=score, feedback=feedback, referenceAnswer="参考", keyPoints=["要点"]
    )


def _batch_output(
    evals: list[QuestionEvaluationOutput],
    score: int = 80,
    feedback: str = "批次评语",
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
) -> BatchEvaluationOutput:
    return BatchEvaluationOutput(
        overallScore=score,
        overallFeedback=feedback,
        strengths=strengths or ["优势1"],
        improvements=improvements or ["改进1"],
        questionEvaluations=evals,
    )


def _summary_output(
    feedback: str = "总评", strengths: list[str] | None = None, improvements: list[str] | None = None
) -> SummaryEvaluationOutput:
    return SummaryEvaluationOutput(
        overallFeedback=feedback, strengths=strengths or ["总优势"], improvements=improvements or ["总改进"]
    )


def _make_graph(
    batch_outputs: list[BatchEvaluationOutput] | None = None,
    summary_output: SummaryEvaluationOutput | None = None,
    batch_raises: bool = False,
    summary_raises: bool = False,
    batch_size: int = 8,
) -> tuple[EvaluationGraph, MagicMock]:
    """构造图 + mock invoker。batch_outputs 按批次顺序返回。"""
    invoker = MagicMock()
    outputs = batch_outputs or []
    call_idx = {"batch": 0}

    async def side_effect(llm, system_prompt, user_prompt, output_model, error_code, error_prefix, log_context):  # noqa: ANN001
        if output_model is BatchEvaluationOutput:
            if batch_raises:
                raise BusinessException(error_code, f"{error_prefix}mock fail")
            idx = call_idx["batch"]
            call_idx["batch"] += 1
            return outputs[idx] if idx < len(outputs) else outputs[-1]
        if output_model is SummaryEvaluationOutput:
            if summary_raises:
                raise BusinessException(error_code, f"{error_prefix}mock fail")
            return summary_output or _summary_output()
        raise AssertionError(f"unexpected output_model: {output_model}")

    invoker.invoke = AsyncMock(side_effect=side_effect)
    graph = EvaluationGraph(invoker=invoker, batch_size=batch_size, semaphore_limit=3)
    return graph, invoker


class TestEvaluateHappyPath:
    async def test_single_batch_reports_scores_and_summary(self) -> None:
        records = [_qa(0, "答0"), _qa(1, "答1")]
        batch = _batch_output([_eval_output(0, 90, "优"), _eval_output(1, 70, "良")])
        graph, _ = _make_graph(batch_outputs=[batch], summary_output=_summary_output("总评语"))

        report = await graph.evaluate(
            chat_client=MagicMock(), session_id="sess1", qa_records=records, resume_text="简历"
        )

        assert isinstance(report, EvaluationReport)
        assert report.session_id == "sess1"
        assert report.total_questions == 2
        # 已答题平均 (90+70)/2 = 80
        assert report.overall_score == 80
        assert report.question_details[0].score == 90
        assert report.question_details[1].score == 70
        assert report.overall_feedback == "总评语"
        assert report.strengths == ["总优势"]
        assert report.improvements == ["总改进"]
        assert report.reference_answers[0].reference_answer == "参考"

    async def test_multiple_batches_merged(self) -> None:
        records = [_qa(i) for i in range(10)]
        batch1 = _batch_output([_eval_output(i, 80) for i in range(4)])
        batch2 = _batch_output([_eval_output(i, 60) for i in range(4, 8)])
        batch3 = _batch_output([_eval_output(i, 100) for i in range(8, 10)])
        graph, _ = _make_graph(batch_outputs=[batch1, batch2, batch3], batch_size=4)

        report = await graph.evaluate(chat_client=MagicMock(), session_id="sess1", qa_records=records, resume_text="")

        assert report.total_questions == 10
        scores = [d.score for d in report.question_details]
        assert scores[:4] == [80, 80, 80, 80]
        assert scores[4:8] == [60, 60, 60, 60]
        assert scores[8:10] == [100, 100]


class TestBatchDegradation:
    async def test_failed_batch_fills_zeros(self) -> None:
        records = [_qa(0, "答0"), _qa(1, "答1")]
        graph, _ = _make_graph(batch_outputs=[], batch_raises=True, summary_raises=True)

        report = await graph.evaluate(chat_client=MagicMock(), session_id="sess1", qa_records=records, resume_text="")

        # 批次全失败 -> 零分兜底（第一级降级）
        assert report.question_details[0].score == 0
        assert report.question_details[1].score == 0
        assert report.overall_score == 0
        # 二级降级：汇总也失败 -> 用批次聚合的默认评语
        assert "未生成有效综合评语" in report.overall_feedback


class TestSummaryDegradation:
    async def test_summary_failure_uses_fallback(self) -> None:
        records = [_qa(0, "答0"), _qa(1, "答1")]
        batch = _batch_output(
            [_eval_output(0, 90, "优"), _eval_output(1, 70, "良")],
            feedback="批次聚合评语",
            strengths=["批次优势"],
            improvements=["批次改进"],
        )
        graph, _ = _make_graph(batch_outputs=[batch], summary_raises=True)

        report = await graph.evaluate(chat_client=MagicMock(), session_id="sess1", qa_records=records, resume_text="")

        # 汇总失败 -> 降级到批次聚合（第二级降级）
        assert report.overall_feedback == "批次聚合评语"
        assert "批次优势" in report.strengths
        assert "批次改进" in report.improvements
        assert report.overall_score == 80


class TestEmptyRecords:
    async def test_empty_records_returns_zero_report(self) -> None:
        graph, _ = _make_graph(batch_outputs=[], summary_output=_summary_output())

        report = await graph.evaluate(chat_client=MagicMock(), session_id="sess1", qa_records=[], resume_text="")

        assert report.total_questions == 0
        assert report.overall_score == 0
        assert report.question_details == []


class TestResumeTruncation:
    async def test_long_resume_truncated_before_llm(self) -> None:
        long_resume = "x" * 5000
        records = [_qa(0, "答0")]
        graph, invoker = _make_graph(batch_outputs=[_batch_output([_eval_output(0, 80)])])

        await graph.evaluate(chat_client=MagicMock(), session_id="sess1", qa_records=records, resume_text=long_resume)

        # 验证传给 invoker 的 user_prompt 含截断标记而非原始长文本
        call = invoker.invoke.call_args_list[0]
        user_prompt = call.kwargs.get("user_prompt") or call.args[2]
        assert "已截断" in user_prompt
        assert "x" * 5000 not in user_prompt


class TestSemaphoreConcurrency:
    async def test_max_in_flight_batches_does_not_exceed_limit(self) -> None:
        # 6 批，semaphore_limit=2 -> 任意时刻在飞批数 <= 2
        import asyncio

        records = [_qa(i) for i in range(6)]
        in_flight = 0
        peak = 0
        lock = asyncio.Lock()

        async def slow_batch(system_prompt, user_prompt, **kw):  # noqa: ANN001
            nonlocal in_flight, peak
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1
            return _batch_output([_eval_output(0, 80)])

        invoker = MagicMock()
        invoker.invoke = AsyncMock(side_effect=slow_batch)
        graph = EvaluationGraph(invoker=invoker, batch_size=1, semaphore_limit=2)

        await graph.evaluate(chat_client=MagicMock(), session_id="sess1", qa_records=records, resume_text="")

        assert peak <= 2
        assert peak >= 2  # 确实并发了


class TestPartialBatchFailure:
    async def test_one_batch_fails_others_succeed(self) -> None:
        records = [_qa(i) for i in range(8)]
        batch_ok = _batch_output([_eval_output(i, 80) for i in range(4)])
        invoker = MagicMock()
        call_idx = {"batch": 0}

        async def side_effect(llm, system_prompt, user_prompt, output_model, error_code, error_prefix, log_context):  # noqa: ANN001
            if output_model is BatchEvaluationOutput:
                idx = call_idx["batch"]
                call_idx["batch"] += 1
                if idx == 1:
                    raise BusinessException(error_code, f"{error_prefix}mock fail")
                return batch_ok
            return _summary_output()

        invoker.invoke = AsyncMock(side_effect=side_effect)
        graph = EvaluationGraph(invoker=invoker, batch_size=4, semaphore_limit=3)

        report = await graph.evaluate(chat_client=MagicMock(), session_id="sess1", qa_records=records, resume_text="")

        scores = [d.score for d in report.question_details]
        # 批0 成功（80），批1 失败（零分兜底）
        assert scores[:4] == [80, 80, 80, 80]
        assert scores[4:] == [0, 0, 0, 0]
