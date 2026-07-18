"""统一评估领域服务单元测试：纯函数算法，无框架依赖。

对照 Java UnifiedEvaluationService 的合并/汇总/报告构建逻辑。
"""

from app.domain.entities.evaluation import (
    BatchReport,
    BatchResult,
    QaRecord,
    QuestionEvaluationItem,
    Summary,
)
from app.domain.entities.interview import InterviewQuestion
from app.domain.services.evaluation import (
    build_category_summary,
    build_qa_records,
    build_qa_records_text,
    build_question_highlights,
    build_report,
    merge_list_items,
    merge_overall_feedback,
    merge_question_evaluations,
    overlay_answers,
    split_batches,
    truncate_reference,
    truncate_resume,
)


def _qa(index: int, question: str = "题", category: str = "JAVA", answer: str | None = "答") -> QaRecord:
    return QaRecord(question_index=index, question=question, category=category, user_answer=answer)


def _eval_item(
    index: int, score: int = 80, feedback: str = "好", ref: str = "参考", keys: list[str] | None = None
) -> QuestionEvaluationItem:
    return QuestionEvaluationItem(
        question_index=index, score=score, feedback=feedback, reference_answer=ref, key_points=keys or []
    )


def _batch_report(
    score: int = 80,
    feedback: str = "批次评语",
    strengths: list[str] | None = None,
    improvements: list[str] | None = None,
    evals: list[QuestionEvaluationItem] | None = None,
) -> BatchReport:
    return BatchReport(
        overall_score=score,
        overall_feedback=feedback,
        strengths=strengths or [],
        improvements=improvements or [],
        question_evaluations=evals or [],
    )


class TestTruncateResume:
    def test_short_resume_unchanged(self) -> None:
        assert truncate_resume("短简历") == "短简历"

    def test_long_resume_truncated_with_marker(self) -> None:
        text = "x" * 3500
        result = truncate_resume(text, limit=3000)
        assert result.startswith("x" * 3000)
        assert "已截断" in result
        assert len(result) < len(text)


class TestTruncateReference:
    def test_none_returns_empty(self) -> None:
        assert truncate_reference(None) == ""

    def test_long_reference_truncated(self) -> None:
        text = "y" * 7000
        result = truncate_reference(text, limit=6000)
        assert result.startswith("y" * 6000)
        assert "已截断" in result


class TestBuildQaRecordsText:
    def test_formats_index_category_question_answer(self) -> None:
        records = [_qa(0, "什么是 JVM", "JAVA", "虚拟机"), _qa(1, "MySQL 索引", "MYSQL", None)]
        text = build_qa_records_text(records)
        assert "问题1 [JAVA]: 什么是 JVM" in text
        assert "回答: 虚拟机" in text
        assert "问题2 [MYSQL]: MySQL 索引" in text
        assert "回答: (未回答)" in text


class TestOverlayAnswers:
    def test_overlays_user_answer_by_index(self) -> None:
        questions = [
            InterviewQuestion(question_index=0, question="Q1", type="JAVA", category="Java"),
            InterviewQuestion(question_index=1, question="Q2", type="MYSQL", category="MySQL"),
        ]
        answer_map = {0: "答1", 1: "答2"}
        result = overlay_answers(questions, answer_map)
        assert result[0].user_answer == "答1"
        assert result[1].user_answer == "答2"

    def test_missing_answer_stays_none(self) -> None:
        questions = [InterviewQuestion(question_index=0, question="Q1", type="JAVA", category="Java")]
        result = overlay_answers(questions, {})
        assert result[0].user_answer is None

    def test_out_of_range_index_ignored(self) -> None:
        questions = [InterviewQuestion(question_index=0, question="Q1", type="JAVA", category="Java")]
        answer_map = {5: "越界"}
        result = overlay_answers(questions, answer_map)
        assert result[0].user_answer is None


class TestBuildQaRecords:
    def test_maps_questions_to_qa_records(self) -> None:
        questions = [
            InterviewQuestion(question_index=0, question="Q1", type="JAVA", category="Java", user_answer="A1"),
            InterviewQuestion(question_index=1, question="Q2", type="MYSQL", category="MySQL"),
        ]
        records = build_qa_records(questions)
        assert records[0].question_index == 0
        assert records[0].question == "Q1"
        assert records[0].category == "Java"
        assert records[0].user_answer == "A1"
        assert records[1].user_answer is None


class TestSplitBatches:
    def test_splits_by_batch_size(self) -> None:
        records = [_qa(i) for i in range(20)]
        batches = split_batches(records, batch_size=8)
        assert len(batches) == 3
        assert batches[0].start_index == 0
        assert batches[0].end_index == 8
        assert len(batches[0].records) == 8
        assert batches[2].start_index == 16
        assert batches[2].end_index == 20
        assert len(batches[2].records) == 4

    def test_single_batch_when_under_limit(self) -> None:
        records = [_qa(i) for i in range(3)]
        batches = split_batches(records, batch_size=8)
        assert len(batches) == 1
        assert batches[0].end_index == 3

    def test_empty_records_returns_empty(self) -> None:
        assert split_batches([], batch_size=8) == []


class TestMergeQuestionEvaluations:
    def test_merges_in_order(self) -> None:
        batch_results = [
            BatchResult(0, 2, _batch_report(evals=[_eval_item(0, 90), _eval_item(1, 70)])),
            BatchResult(2, 4, _batch_report(evals=[_eval_item(2, 60), _eval_item(3, 85)])),
        ]
        merged = merge_question_evaluations(batch_results)
        assert [m.score for m in merged] == [90, 70, 60, 85]

    def test_failed_batch_fills_zeros(self) -> None:
        batch_results = [
            BatchResult(0, 2, None),
            BatchResult(2, 4, _batch_report(evals=[_eval_item(2, 60), _eval_item(3, 85)])),
        ]
        merged = merge_question_evaluations(batch_results)
        assert merged[0].score == 0
        assert "0 分" in merged[0].feedback
        assert merged[1].score == 0
        assert merged[2].score == 60

    def test_short_eval_list_fills_remaining_zeros(self) -> None:
        batch_results = [BatchResult(0, 3, _batch_report(evals=[_eval_item(0, 90)]))]
        merged = merge_question_evaluations(batch_results)
        assert merged[0].score == 90
        assert merged[1].score == 0
        assert merged[2].score == 0


class TestMergeOverallFeedback:
    def test_joins_non_blank_with_double_newline(self) -> None:
        batch_results = [
            BatchResult(0, 2, _batch_report(feedback="批1")),
            BatchResult(2, 4, _batch_report(feedback="批2")),
        ]
        assert merge_overall_feedback(batch_results) == "批1\n\n批2"

    def test_all_blank_returns_default(self) -> None:
        batch_results = [BatchResult(0, 2, None), BatchResult(2, 4, _batch_report(feedback=""))]
        result = merge_overall_feedback(batch_results)
        assert "未生成有效综合评语" in result


class TestMergeListItems:
    def test_merges_strengths_dedup_limit_8(self) -> None:
        batch_results = [
            BatchResult(0, 2, _batch_report(strengths=["a", "b", "a"])),
            BatchResult(2, 4, _batch_report(strengths=["b", "c"])),
        ]
        result = merge_list_items(batch_results, strengths_mode=True)
        assert result == ["a", "b", "c"]

    def test_limits_to_8(self) -> None:
        items = [f"s{i}" for i in range(12)]
        batch_results = [BatchResult(0, 2, _batch_report(strengths=items))]
        assert len(merge_list_items(batch_results, strengths_mode=True)) == 8

    def test_improvements_mode(self) -> None:
        batch_results = [BatchResult(0, 2, _batch_report(improvements=["改进1"]))]
        assert merge_list_items(batch_results, strengths_mode=False) == ["改进1"]


class TestBuildCategorySummary:
    def test_groups_by_category_with_avg(self) -> None:
        records = [
            _qa(0, category="JAVA", answer="a"),
            _qa(1, category="JAVA", answer="b"),
            _qa(2, category="MYSQL", answer="c"),
        ]
        evals = [_eval_item(0, 80), _eval_item(1, 60), _eval_item(2, 90)]
        summary = build_category_summary(records, evals)
        assert "JAVA" in summary
        assert "平均分 70" in summary
        assert "题数 2" in summary
        assert "MYSQL" in summary

    def test_unanswered_excluded_from_avg(self) -> None:
        records = [_qa(0, category="JAVA", answer=None), _qa(1, category="JAVA", answer="b")]
        evals = [_eval_item(0, 50), _eval_item(1, 80)]
        summary = build_category_summary(records, evals)
        assert "平均分 80" in summary


class TestBuildQuestionHighlights:
    def test_formats_each_question(self) -> None:
        records = [_qa(0, question="什么是 JVM", answer="a"), _qa(1, question="MySQL 索引", answer="b")]
        evals = [_eval_item(0, 90, "好"), _eval_item(1, 60, "差")]
        highlights = build_question_highlights(records, evals)
        assert "Q1" in highlights
        assert "什么是 JVM" in highlights
        assert "分数:90" in highlights
        assert "Q2" in highlights

    def test_truncates_long_question_and_feedback(self) -> None:
        long_q = "问" * 100
        long_f = "反" * 100
        records = [_qa(0, question=long_q, answer="a")]
        evals = [_eval_item(0, 50, long_f)]
        highlights = build_question_highlights(records, evals)
        assert "..." in highlights

    def test_limits_to_20(self) -> None:
        records = [_qa(i) for i in range(25)]
        evals = [_eval_item(i) for i in range(25)]
        highlights = build_question_highlights(records, evals)
        assert highlights.count("\n") <= 20


class TestBuildReport:
    def test_overall_score_is_answered_average(self) -> None:
        records = [
            _qa(0, answer="a"),
            _qa(1, answer="b"),
            _qa(2, answer=None),
        ]
        evals = [_eval_item(0, 90), _eval_item(1, 70), _eval_item(2, 0)]
        summary = Summary(overall_feedback="总评", strengths=["优"], improvements=["缺"])
        report = build_report("sess1", records, evals, summary)
        # 已答题 2 道，平均 (90+70)/2 = 80
        assert report.overall_score == 80
        assert report.total_questions == 3
        assert report.session_id == "sess1"

    def test_all_unanswered_scores_zero(self) -> None:
        records = [_qa(0, answer=None), _qa(1, answer=None)]
        evals = [_eval_item(0, 0), _eval_item(1, 0)]
        summary = Summary(overall_feedback="总评", strengths=[], improvements=[])
        report = build_report("sess1", records, evals, summary)
        assert report.overall_score == 0

    def test_category_scores_computed(self) -> None:
        records = [
            _qa(0, category="JAVA", answer="a"),
            _qa(1, category="JAVA", answer="b"),
            _qa(2, category="MYSQL", answer="c"),
        ]
        evals = [_eval_item(0, 80), _eval_item(1, 60), _eval_item(2, 90)]
        summary = Summary(overall_feedback="总评", strengths=[], improvements=[])
        report = build_report("sess1", records, evals, summary)
        cat_map = {c.category: c for c in report.category_scores}
        assert cat_map["JAVA"].score == 70
        assert cat_map["JAVA"].question_count == 2
        assert cat_map["MYSQL"].score == 90

    def test_question_details_and_reference_answers_built(self) -> None:
        records = [_qa(0, question="Q1", category="JAVA", answer="A1")]
        evals = [_eval_item(0, 90, "好", "参考答案", ["要点1"])]
        summary = Summary(overall_feedback="总评", strengths=["优"], improvements=["缺"])
        report = build_report("sess1", records, evals, summary)
        assert report.question_details[0].question == "Q1"
        assert report.question_details[0].score == 90
        assert report.reference_answers[0].reference_answer == "参考答案"
        assert report.reference_answers[0].key_points == ["要点1"]
        assert report.strengths == ["优"]
        assert report.improvements == ["缺"]
        assert report.overall_feedback == "总评"

    def test_missing_eval_uses_zero_and_default_feedback(self) -> None:
        records = [_qa(0, answer="a"), _qa(1, answer="b")]
        evals = [_eval_item(0, 90)]
        # 第二题无 eval
        summary = Summary(overall_feedback="总评", strengths=[], improvements=[])
        report = build_report("sess1", records, evals, summary)
        assert report.question_details[1].score == 0
        assert "未成功生成" in report.question_details[1].feedback

    def test_category_score_excludes_unanswered_from_denominator(self) -> None:
        # JAVA 同步：未回答不计入分类平均分分母（与 overall_score / build_category_summary 一致）
        records = [
            _qa(0, category="JAVA", answer="a"),
            _qa(1, category="JAVA", answer=None),
            _qa(2, category="MYSQL", answer="c"),
        ]
        evals = [_eval_item(0, 80), _eval_item(1, 0), _eval_item(2, 90)]
        summary = Summary(overall_feedback="总评", strengths=[], improvements=[])
        report = build_report("sess1", records, evals, summary)
        cat_map = {c.category: c for c in report.category_scores}
        # JAVA 分类：仅 1 题已答(80) -> 平均 80（未回答的 0 分不计入分母）
        assert cat_map["JAVA"].score == 80
        assert cat_map["JAVA"].question_count == 1
        # overall 同样仅计已答题：仅 JAVA(80) 与 MYSQL(90) 已答 -> (80+90)/2=85
        assert report.overall_score == 85
