import asyncio
import json
import logging
import os
from typing import Protocol

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.resume import Resume, ResumeAnalysis

logger = logging.getLogger(__name__)

_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "static", "fonts")
_FONT_FILENAME = "ZhuqueFangsong-Regular.ttf"

_DIMENSIONS: list[tuple[str, str, int]] = [
    ("项目经验", "project_score", 40),
    ("技能匹配度", "skill_match_score", 20),
    ("内容完整性", "content_score", 15),
    ("结构清晰度", "structure_score", 15),
    ("表达专业性", "expression_score", 10),
]


class PdfRenderer(Protocol):
    def render(self, html: str) -> bytes: ...


class WeasyPrintRenderer:
    """基于 WeasyPrint 的真实渲染器，懒加载 weasyprint（容器内可用，本机 Windows 缺原生库时不影响导入）。"""

    def render(self, html: str) -> bytes:
        from typing import cast

        from weasyprint import HTML  # type: ignore[import-untyped]

        return cast(bytes, HTML(string=html, base_url=_FONT_DIR).write_pdf())


class PdfExportService:
    """简历分析报告 PDF 导出：构建 HTML（含中文字体）并委托 renderer 渲染。"""

    def __init__(self, renderer: PdfRenderer) -> None:
        self._renderer = renderer

    async def export_resume_analysis(self, resume: Resume, analysis: ResumeAnalysis) -> bytes:
        html = self._build_html(resume, analysis)
        try:
            return await asyncio.to_thread(self._renderer.render, html)
        except Exception as e:
            logger.error("PDF 导出失败: resumeId=%s, error=%s", resume.id, e)
            raise BusinessException(ErrorCode.EXPORT_PDF_FAILED, f"PDF导出失败: {e}") from e

    def _build_html(self, resume: Resume, analysis: ResumeAnalysis) -> str:
        font_face = self._font_face_css()
        uploaded = resume.uploaded_at.strftime("%Y-%m-%d %H:%M:%S") if resume.uploaded_at else "未知"

        strengths = self._parse_strengths(analysis.strengths_json)
        suggestions = self._parse_suggestions(analysis.suggestions_json)

        rows = "\n".join(
            f"<tr><td>{label}</td><td>{getattr(analysis, field) or 0} / {max_score}</td></tr>"
            for label, field, max_score in _DIMENSIONS
        )

        strengths_html = "".join(f"<li>{self._escape(s)}</li>" for s in strengths) if strengths else "<p>暂无</p>"

        suggestions_html = (
            "".join(
                f"<div class='suggestion'>"
                f"<b>【{self._escape(s.get('priority', ''))}】{self._escape(s.get('category', ''))}</b>"
                f"<p>问题：{self._escape(s.get('issue', ''))}</p>"
                f"<p>建议：{self._escape(s.get('recommendation', ''))}</p></div>"
                for s in suggestions
            )
            if suggestions
            else "<p>暂无</p>"
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
{font_face}
body {{ font-family: "ZhuqueFangsong", "Microsoft YaHei", "SimSun", sans-serif; padding: 40px; }}
h1 {{ text-align: center; color: #2980b9; }}
h2 {{ color: #34495e; border-bottom: 2px solid #2980b9; padding-bottom: 5px; }}
table {{ width: 100%; border-collapse: collapse; }}
td {{ border: 1px solid #ccc; padding: 8px; }}
.score {{ font-size: 24px; font-weight: bold; }}
.suggestion {{ margin-bottom: 12px; padding: 8px; background: #f9f9f9; }}
</style>
</head>
<body>
<h1>简历分析报告</h1>
<h2>基本信息</h2>
<p>文件名：{self._escape(resume.original_filename)}</p>
<p>上传时间：{uploaded}</p>
<h2>综合评分</h2>
<p class="score">{analysis.overall_score or 0} / 100</p>
<h2>各维度评分</h2>
<table>{rows}</table>
<h2>简历摘要</h2>
<p>{self._escape(analysis.summary or "")}</p>
<h2>优势亮点</h2>
<ul>{strengths_html}</ul>
<h2>改进建议</h2>
{suggestions_html}
</body>
</html>"""

    def _font_face_css(self) -> str:
        font_path = os.path.join(_FONT_DIR, _FONT_FILENAME)
        if os.path.exists(font_path):
            return f'@font-face {{ font-family: "ZhuqueFangsong"; src: url("{_FONT_FILENAME}"); }}'
        return ""

    def _parse_strengths(self, raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return [str(s) for s in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    def _parse_suggestions(self, raw: str | None) -> list[dict[str, object]]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return [s for s in parsed if isinstance(s, dict)] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    def _escape(self, text: object) -> str:
        if text is None:
            return ""
        s = str(text)
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
