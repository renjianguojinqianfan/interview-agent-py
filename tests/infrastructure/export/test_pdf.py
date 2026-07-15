import json
from datetime import datetime

import pytest

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
