import json
from datetime import datetime

import pytest

from app.domain.entities.evaluation import (
    CategoryScore,
    EvaluationReport,
    QuestionEvaluation,
    ReferenceAnswer,
)
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM
from app.infrastructure.db.models.resume import Resume, ResumeAnalysis
from app.infrastructure.export.pdf import PdfExportService


def _make_resume() -> Resume:
    return Resume(
        id=1,
        file_hash="h",
        original_filename="张三_resume.pdf",
        file_size=1024,
        uploaded_at=datetime(2026, 7, 16, 10, 0, 0),
        resume_text="text",
        analyze_status="COMPLETED",
    )


def _make_analysis() -> ResumeAnalysis:
    return ResumeAnalysis(
        id=1,
        resume_id=1,
        overall_score=85,
        content_score=13,
        structure_score=12,
        skill_match_score=18,
        expression_score=7,
        project_score=35,
        summary="资深 Java 工程师，项目经验扎实",
        strengths_json=json.dumps(["高并发经验丰富", "分布式设计能力强"], ensure_ascii=False),
        suggestions_json=json.dumps(
            [{"category": "项目", "priority": "高", "issue": "描述笼统", "recommendation": "加量化指标"}],
            ensure_ascii=False,
        ),
        analyzed_at=datetime(2026, 7, 16, 11, 0, 0),
    )


class _CapturingRenderer:
    def __init__(self) -> None:
        self.captured_html: str = ""
        self.output = b"%PDF-1.4 fake pdf bytes"

    def render(self, html: str) -> bytes:
        self.captured_html = html
        return self.output


@pytest.fixture()
def service() -> PdfExportService:
    return PdfExportService(renderer=_CapturingRenderer())


class TestExportResumeAnalysis:
    async def test_returns_renderer_output(self, service: PdfExportService) -> None:
        result = await service.export_resume_analysis(_make_resume(), _make_analysis())

        assert result == b"%PDF-1.4 fake pdf bytes"

    async def test_html_contains_title(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        service = PdfExportService(renderer=renderer)

        await service.export_resume_analysis(_make_resume(), _make_analysis())

        assert "简历分析报告" in renderer.captured_html

    async def test_html_contains_overall_score(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        service = PdfExportService(renderer=renderer)

        await service.export_resume_analysis(_make_resume(), _make_analysis())

        assert "85" in renderer.captured_html
        assert "100" in renderer.captured_html

    async def test_html_contains_all_dimension_scores(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        service = PdfExportService(renderer=renderer)

        await service.export_resume_analysis(_make_resume(), _make_analysis())

        html = renderer.captured_html
        assert "项目经验" in html and "40" in html
        assert "技能匹配度" in html and "20" in html
        assert "内容完整性" in html and "15" in html
        assert "结构清晰度" in html and "15" in html
        assert "表达专业性" in html and "10" in html

    async def test_html_contains_strengths(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        service = PdfExportService(renderer=renderer)

        await service.export_resume_analysis(_make_resume(), _make_analysis())

        assert "高并发经验丰富" in renderer.captured_html
        assert "分布式设计能力强" in renderer.captured_html

    async def test_html_contains_suggestions(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        service = PdfExportService(renderer=renderer)

        await service.export_resume_analysis(_make_resume(), _make_analysis())

        html = renderer.captured_html
        assert "项目" in html
        assert "描述笼统" in html
        assert "加量化指标" in html

    async def test_html_contains_filename(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        service = PdfExportService(renderer=renderer)

        await service.export_resume_analysis(_make_resume(), _make_analysis())

        assert "张三_resume.pdf" in renderer.captured_html

    async def test_html_references_chinese_font(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        service = PdfExportService(renderer=renderer)

        await service.export_resume_analysis(_make_resume(), _make_analysis())

        assert "ZhuqueFangsong" in renderer.captured_html or "@font-face" in renderer.captured_html

    async def test_handles_empty_strengths_and_suggestions(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        service = PdfExportService(renderer=renderer)
        analysis = _make_analysis()
        analysis.strengths_json = None
        analysis.suggestions_json = None

        result = await service.export_resume_analysis(_make_resume(), analysis)

        assert result == b"%PDF-1.4 fake pdf bytes"
        assert "优势" not in renderer.captured_html or "暂无" in renderer.captured_html


def _make_interview_session_orm() -> InterviewSessionORM:
    return InterviewSessionORM(
        id=1,
        session_id="sess123",
        skill_id="java-backend",
        difficulty="mid",
        total_questions=2,
        current_question_index=2,
        status="EVALUATED",
        created_at=datetime(2026, 7, 18, 10, 0, 0),
        completed_at=datetime(2026, 7, 18, 11, 0, 0),
    )


def _make_evaluation_report() -> EvaluationReport:
    return EvaluationReport(
        session_id="sess123",
        total_questions=2,
        overall_score=85,
        category_scores=[CategoryScore(category="Java", score=85, question_count=2)],
        question_details=[
            QuestionEvaluation(0, "什么是 JVM", "Java", "虚拟机", 92, "源码级理解"),
            QuestionEvaluation(1, "MySQL 索引", "Java", "B+树", 50, "概念有误"),
        ],
        overall_feedback="整体表现良好",
        strengths=["基础扎实"],
        improvements=["需补 MySQL"],
        reference_answers=[
            ReferenceAnswer(0, "什么是 JVM", "JVM 是 Java 虚拟机...", ["字节码", "内存模型"]),
            ReferenceAnswer(1, "MySQL 索引", "B+树索引结构...", ["聚簇索引"]),
        ],
    )


class TestExportInterviewReport:
    async def test_returns_renderer_output(self, service: PdfExportService) -> None:
        result = await service.export_interview_report(_make_interview_session_orm(), _make_evaluation_report())
        assert result == b"%PDF-1.4 fake pdf bytes"

    async def test_html_contains_title(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        await svc.export_interview_report(_make_interview_session_orm(), _make_evaluation_report())
        assert "面试报告" in renderer.captured_html

    async def test_html_contains_overall_score(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        await svc.export_interview_report(_make_interview_session_orm(), _make_evaluation_report())
        assert "85" in renderer.captured_html

    async def test_overall_score_color_aligned_to_prompt_band(self, service: PdfExportService) -> None:
        # 85 属 75-89 良好 -> 蓝色 #2980b9
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        await svc.export_interview_report(_make_interview_session_orm(), _make_evaluation_report())
        assert "#2980b9" in renderer.captured_html

    async def test_per_question_scores_use_distinct_colors(self, service: PdfExportService) -> None:
        # 题0=92(>=90 绿 #27ae60)，题1=50(<60 红 #e74c3c)
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        await svc.export_interview_report(_make_interview_session_orm(), _make_evaluation_report())
        assert "#27ae60" in renderer.captured_html
        assert "#e74c3c" in renderer.captured_html

    async def test_html_contains_question_and_feedback(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        await svc.export_interview_report(_make_interview_session_orm(), _make_evaluation_report())
        html = renderer.captured_html
        assert "什么是 JVM" in html
        assert "源码级理解" in html
        assert "虚拟机" in html

    async def test_html_contains_reference_answers_and_key_points(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        await svc.export_interview_report(_make_interview_session_orm(), _make_evaluation_report())
        html = renderer.captured_html
        assert "JVM 是 Java 虚拟机" in html
        assert "字节码" in html
        assert "聚簇索引" in html

    async def test_html_contains_strengths_and_improvements(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        await svc.export_interview_report(_make_interview_session_orm(), _make_evaluation_report())
        html = renderer.captured_html
        assert "基础扎实" in html
        assert "需补 MySQL" in html
        assert "整体表现良好" in html

    async def test_html_contains_category_scores(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        await svc.export_interview_report(_make_interview_session_orm(), _make_evaluation_report())
        html = renderer.captured_html
        assert "Java" in html

    async def test_html_references_chinese_font(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        await svc.export_interview_report(_make_interview_session_orm(), _make_evaluation_report())
        assert "ZhuqueFangsong" in renderer.captured_html or "@font-face" in renderer.captured_html

    async def test_reference_answer_matched_by_question_index_not_position(self) -> None:
        """PDF 参考答案按 question_index 匹配，非位置下标。

        验证 R3 review finding (c).2 修复：question_details 缺中间题时，
        reference_answers 不应错位（旧代码用 enumerate 位置下标取 reference_answers[index]）。
        """
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        report = EvaluationReport(
            session_id="sess123",
            total_questions=3,
            overall_score=70,
            category_scores=[],
            question_details=[
                QuestionEvaluation(0, "Q0-text", "Java", "A0", 90, "f0"),
                QuestionEvaluation(2, "Q2-text", "Java", "A2", 50, "f2"),
            ],
            overall_feedback="",
            strengths=[],
            improvements=[],
            reference_answers=[
                ReferenceAnswer(0, "Q0-text", "Ref-Q0", ["kp0"]),
                ReferenceAnswer(1, "Q1-text", "Ref-Q1", ["kp1"]),
                ReferenceAnswer(2, "Q2-text", "Ref-Q2", ["kp2"]),
            ],
        )
        await svc.export_interview_report(_make_interview_session_orm(), report)

        html = renderer.captured_html
        # Q2 (question_index=2) 应显示为 Q3，非 Q2（位置下标+1=2）
        assert "Q3" in html
        # Q0 的参考答案应是 Ref-Q0
        assert "Ref-Q0" in html
        # Q2 的参考答案应是 Ref-Q2，不应错位为 Ref-Q1
        assert "Ref-Q2" in html
        assert "Ref-Q1" not in html

    async def test_unanswered_question_renders_not_answered_marker(self) -> None:
        """未回答题 PDF 渲染：user_answer=None 显示(未回答)，参考答案按 question_index 匹配。"""
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        report = EvaluationReport(
            session_id="sess123",
            total_questions=2,
            overall_score=90,
            category_scores=[],
            question_details=[
                QuestionEvaluation(0, "Q0-text", "Java", "A0", 90, "f0"),
                QuestionEvaluation(1, "Q1-text", "Java", None, 0, "该题未作答。"),
            ],
            overall_feedback="",
            strengths=[],
            improvements=[],
            reference_answers=[
                ReferenceAnswer(0, "Q0-text", "Ref-Q0", []),
                ReferenceAnswer(1, "Q1-text", "Ref-Q1", []),
            ],
        )
        await svc.export_interview_report(_make_interview_session_orm(), report)

        html = renderer.captured_html
        # 未回答题显示(未回答)
        assert "(未回答)" in html
        # 未回答题的参考答案仍正确匹配
        assert "Ref-Q1" in html
        # 未回答题的反馈文案
        assert "该题未作答。" in html

    async def test_handles_empty_strengths_and_improvements(self, service: PdfExportService) -> None:
        renderer = _CapturingRenderer()
        svc = PdfExportService(renderer=renderer)
        report = _make_evaluation_report()
        report = EvaluationReport(
            session_id=report.session_id,
            total_questions=report.total_questions,
            overall_score=report.overall_score,
            category_scores=report.category_scores,
            question_details=report.question_details,
            overall_feedback="",
            strengths=[],
            improvements=[],
            reference_answers=report.reference_answers,
        )
        result = await svc.export_interview_report(_make_interview_session_orm(), report)
        assert result == b"%PDF-1.4 fake pdf bytes"
