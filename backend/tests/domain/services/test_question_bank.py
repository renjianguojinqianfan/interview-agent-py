"""question_bank 领域纯函数单测。"""

import random

import pytest

from app.domain.entities.evaluation import EvaluationReport, ReferenceAnswer
from app.domain.entities.interview import InterviewQuestion
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.question_bank import (
    QuestionBankFollowUp,
    QuestionCandidate,
    apply_question_references,
    assemble_interview_questions,
    build_question_reference_context,
    calculate_interview_capacity,
    normalize_question_key,
    trim_to_none,
)


class TestNormalizeQuestionKey:
    def test_strips_whitespace_punctuation_and_case(self) -> None:
        assert normalize_question_key("什么是 Redis？") == normalize_question_key("什么是redis")

    def test_nfc_normalization(self) -> None:
        # "é" 组合形式（e + U+0301）与预组合形式（U+00E9）归一后相同
        assert normalize_question_key("caf\u00e9") == normalize_question_key("cafe\u0301")

    def test_none_and_blank_yield_empty_key(self) -> None:
        assert normalize_question_key(None) == ""
        assert normalize_question_key("  ？！ ") == ""

    def test_distinct_questions_have_distinct_keys(self) -> None:
        assert normalize_question_key("什么是缓存穿透") != normalize_question_key("什么是缓存击穿")


class TestTrimToNone:
    def test_blank_variants_become_none(self) -> None:
        assert trim_to_none(None) is None
        assert trim_to_none("") is None
        assert trim_to_none("   ") is None

    def test_trims_surrounding_whitespace(self) -> None:
        assert trim_to_none("  题干  ") == "题干"


def _follow_up(question: str = "追问", **overrides: object) -> QuestionBankFollowUp:
    defaults: dict = {
        "question": question,
        "reference_answer": "追问答案",
        "key_points": ["要点"],
        "scoring_rubric": "追问规则",
    }
    defaults.update(overrides)
    return QuestionBankFollowUp(**defaults)


def _candidate(question: str = "什么是缓存穿透？", follow_up_count: int = 2, **overrides: object) -> QuestionCandidate:
    defaults: dict = {
        "question": question,
        "type": "REDIS",
        "category": "Redis",
        "topic_summary": "缓存穿透",
        "reference_answer": "参考答案",
        "key_points": ["要点A", "要点B"],
        "scoring_rubric": "10分制",
        "source_context": "原文片段",
        "follow_ups": [_follow_up(f"追问{i}") for i in range(follow_up_count)],
    }
    defaults.update(overrides)
    return QuestionCandidate(**defaults)


class TestAssembleInterviewQuestions:
    def test_fixed_seed_reproducible(self) -> None:
        candidates = [_candidate(f"题{i}") for i in range(6)]

        first = assemble_interview_questions(candidates, 3, 1, random.Random(42), "mid")
        second = assemble_interview_questions(candidates, 3, 1, random.Random(42), "mid")

        assert [q.question for q in first] == [q.question for q in second]

    def test_main_and_follow_up_structure(self) -> None:
        questions = assemble_interview_questions([_candidate()], 1, 2, random.Random(1), "mid")

        assert len(questions) == 3  # 1 主问题 + 2 追问
        main = questions[0]
        assert main.question_index == 0
        assert not main.is_follow_up
        assert main.reference_answer == "参考答案"
        assert main.key_points == ["要点A", "要点B"]
        assert main.scoring_rubric == "10分制"
        assert main.source_context == "原文片段"
        for follow_up in questions[1:]:
            assert follow_up.is_follow_up
            assert follow_up.parent_question_index == 0
            assert follow_up.reference_answer == "追问答案"
            assert follow_up.source_context == "原文片段"
        assert [q.question_index for q in questions] == [0, 1, 2]

    def test_type_and_category_fallbacks(self) -> None:
        candidate = _candidate(type=None, category=None, follow_up_count=1)

        questions = assemble_interview_questions([candidate], 1, 1, random.Random(1), "mid")

        assert questions[0].type == "KNOWLEDGE_BASE"
        assert questions[0].category == "知识库"
        assert questions[1].type == "KNOWLEDGE_BASE"
        assert questions[1].category == "知识库追问"

    def test_insufficient_candidates_raises_with_details(self) -> None:
        candidates = [_candidate("题A", follow_up_count=0), _candidate("题B", follow_up_count=2)]

        with pytest.raises(BusinessException) as exc:
            assemble_interview_questions(candidates, 2, 1, random.Random(1), "senior", category="Redis")

        assert exc.value.error_code is ErrorCode.INTERVIEW_QUESTION_INSUFFICIENT
        message = exc.value.message
        assert "2" in message and "1" in message
        assert "Redis" in message and "senior" in message

    def test_insufficient_message_uses_all_categories_when_none(self) -> None:
        with pytest.raises(BusinessException) as exc:
            assemble_interview_questions([], 1, 0, random.Random(1), "mid")

        assert "全部方向" in exc.value.message

    def test_follow_up_sampling_strict_count(self) -> None:
        candidate = _candidate(follow_up_count=5)

        questions = assemble_interview_questions([candidate], 1, 3, random.Random(7), "mid")

        follow_ups = [q for q in questions if q.is_follow_up]
        assert len(follow_ups) == 3
        assert len({q.question for q in follow_ups}) == 3  # 无重复抽取


class TestCalculateInterviewCapacity:
    def test_category_options_sorted_count_desc_then_name(self) -> None:
        candidates = [
            _candidate("题1", category="Redis"),
            _candidate("题2", category="MySQL"),
            _candidate("题3", category="MySQL"),
            _candidate("题4", category="JVM"),
            _candidate("题5", category=None),  # 空方向排除
        ]

        categories, _ = calculate_interview_capacity(candidates, None, 2)

        assert [(c.category, c.available_question_count) for c in categories] == [
            ("MySQL", 2),
            ("JVM", 1),
            ("Redis", 1),
        ]

    def test_follow_up_options_matrix_scoped_by_category(self) -> None:
        candidates = [
            _candidate("题1", category="Redis", follow_up_count=2),
            _candidate("题2", category="Redis", follow_up_count=0),
            _candidate("题3", category="MySQL", follow_up_count=5),
        ]

        categories, options = calculate_interview_capacity(candidates, "Redis", 1)

        # categories 始终基于全量（不受 category 过滤）
        assert {c.category for c in categories} == {"Redis", "MySQL"}
        assert len(options) == 6  # 0~5 档位
        by_count = {o.follow_up_count: o for o in options}
        assert by_count[0].available_question_count == 2
        assert by_count[2].available_question_count == 1
        assert by_count[3].available_question_count == 0
        assert by_count[2].selectable is True
        assert by_count[3].selectable is False

    def test_selectable_requires_positive_main_count(self) -> None:
        _, options = calculate_interview_capacity([_candidate()], None, 0)

        assert all(not o.selectable for o in options)


def _bank_question(index: int = 0, **overrides: object) -> InterviewQuestion:
    defaults: dict = {
        "question_index": index,
        "question": f"题{index}",
        "type": "KNOWLEDGE_BASE",
        "category": "Redis",
        "reference_answer": "题库答案",
        "key_points": ["要点A"],
        "scoring_rubric": "规则",
    }
    defaults.update(overrides)
    return InterviewQuestion(**defaults)


class TestBuildQuestionReferenceContext:
    def test_concatenates_reference_fields(self) -> None:
        context = build_question_reference_context([_bank_question(0)])

        assert "问题1: 题0" in context
        assert "参考答案: 题库答案" in context
        assert "评分要点: 要点A" in context
        assert "评分规则: 规则" in context

    def test_skips_questions_without_reference(self) -> None:
        plain = _bank_question(1, reference_answer=None, key_points=[], scoring_rubric=None)

        assert build_question_reference_context([plain]) == ""

    def test_rubric_only_question_included(self) -> None:
        rubric_only = _bank_question(2, reference_answer=None, key_points=[], scoring_rubric="只有规则")

        context = build_question_reference_context([rubric_only])

        assert "评分规则: 只有规则" in context
        assert "参考答案" not in context


def _report(references: list[ReferenceAnswer]) -> EvaluationReport:
    return EvaluationReport(
        session_id="s1",
        total_questions=2,
        overall_score=80,
        category_scores=[],
        question_details=[],
        overall_feedback="总评",
        strengths=[],
        improvements=[],
        reference_answers=references,
    )


class TestApplyQuestionReferences:
    def test_overrides_with_bank_answer(self) -> None:
        report = _report([ReferenceAnswer(0, "题0", "LLM答案", ["LLM要点"])])

        result = apply_question_references(report, [_bank_question(0)])

        ref = result.reference_answers[0]
        assert ref.reference_answer == "题库答案"
        assert ref.key_points == ["要点A"]
        assert ref.question_index == 0
        assert ref.question == "题0"  # 保留 report 原题干
        assert result.overall_score == 80  # 其余字段不变

    def test_keeps_llm_reference_when_bank_blank(self) -> None:
        report = _report([ReferenceAnswer(1, "题1", "LLM答案", ["LLM要点"])])
        plain = _bank_question(1, reference_answer="  ")

        result = apply_question_references(report, [plain])

        assert result.reference_answers[0].reference_answer == "LLM答案"

    def test_keeps_reference_when_question_missing(self) -> None:
        report = _report([ReferenceAnswer(9, "题9", "LLM答案", [])])

        result = apply_question_references(report, [_bank_question(0)])

        assert result.reference_answers[0].reference_answer == "LLM答案"

    def test_no_bank_reference_returns_report_unchanged(self) -> None:
        report = _report([ReferenceAnswer(0, "题0", "LLM答案", [])])
        plain = _bank_question(0, reference_answer=None, key_points=[], scoring_rubric=None)

        result = apply_question_references(report, [plain])

        assert result == report
