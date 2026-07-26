from unittest.mock import patch

import pytest

from app.infrastructure.parsing.text_cleaner import TextCleaner


class TestParseContentUnit:
    def test_parses_txt_bytes_directly(self) -> None:
        from app.infrastructure.parsing.parser import DocumentParser

        parser = DocumentParser(TextCleaner())
        result = parser.parse_content(b"Hello\nWorld", "test.txt")
        assert "Hello" in result
        assert "World" in result

    def test_empty_bytes_returns_empty(self) -> None:
        from app.infrastructure.parsing.parser import DocumentParser

        parser = DocumentParser(TextCleaner())
        assert parser.parse_content(b"", "empty.txt") == ""

    def test_cleans_parsed_text(self) -> None:
        from app.infrastructure.parsing.parser import DocumentParser

        parser = DocumentParser(TextCleaner())
        raw = "line1\n---\nline2\nimage1.png\n"
        result = parser.parse_content(raw.encode("utf-8"), "test.txt")
        assert "---" not in result
        assert "image1.png" not in result
        assert "line1" in result
        assert "line2" in result

    def test_parses_pdf_via_unstructured(self) -> None:
        from app.infrastructure.parsing.parser import DocumentParser

        parser = DocumentParser(TextCleaner())

        fake_elements = ["PDF page 1 content", "PDF page 2 content"]

        with patch("app.infrastructure.parsing.parser._partition_pdf") as mock_partition:
            mock_partition.return_value = fake_elements
            result = parser.parse_content(b"fake-pdf-bytes", "doc.pdf")
            assert "PDF page 1 content" in result
            assert "PDF page 2 content" in result
            mock_partition.assert_called_once()

    def test_pdf_partition_uses_pdfminer_without_inference_deps(self) -> None:
        """#51：PDF 解析直接走 pdfminer 纯文本抽取，不得 import unstructured.partition.pdf
        （该模块 import 即硬依赖 unstructured-inference/torch）。"""
        from app.infrastructure.parsing.parser import _partition_pdf

        with patch("pdfminer.high_level.extract_text") as mock_extract:
            mock_extract.return_value = "PDF 文本内容"
            elements = _partition_pdf(b"fake-pdf-bytes")
            mock_extract.assert_called_once()
            assert elements == ["PDF 文本内容"]

    def test_pdf_partition_empty_text_returns_no_elements(self) -> None:
        """#51：扫描件无文本层时返回空元素，由上游空文本校验给出友好报错。"""
        from app.infrastructure.parsing.parser import _partition_pdf

        with patch("pdfminer.high_level.extract_text") as mock_extract:
            mock_extract.return_value = "   \n "
            assert _partition_pdf(b"fake-pdf-bytes") == []

    def test_parses_docx_via_unstructured(self) -> None:
        from app.infrastructure.parsing.parser import DocumentParser

        parser = DocumentParser(TextCleaner())

        fake_elements = ["DOCX paragraph 1"]

        with patch("app.infrastructure.parsing.parser._partition_docx") as mock_partition:
            mock_partition.return_value = fake_elements
            result = parser.parse_content(b"fake-docx-bytes", "doc.docx")
            assert "DOCX paragraph 1" in result

    def test_unstructured_failure_raises_business_exception(self) -> None:
        from app.domain.errors import BusinessException
        from app.infrastructure.parsing.parser import DocumentParser

        parser = DocumentParser(TextCleaner())

        with patch("app.infrastructure.parsing.parser._partition_pdf") as mock_partition:
            mock_partition.side_effect = RuntimeError("parse failed")
            with pytest.raises(BusinessException):
                parser.parse_content(b"fake-pdf-bytes", "doc.pdf")


class TestParseContentIntegration:
    def test_parses_real_txt_file(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from app.infrastructure.parsing.parser import DocumentParser

        file_path = tmp_path / "sample.txt"
        file_path.write_text("姓名：张三\n技能：Java, Python, Spring Boot\n经验：5年", encoding="utf-8")

        parser = DocumentParser(TextCleaner())
        content = file_path.read_bytes()
        result = parser.parse_content(content, "sample.txt")
        assert "张三" in result
        assert "Java" in result
        assert "Spring Boot" in result

    def test_parses_real_pdf_without_inference_deps(self) -> None:
        """#51：真实文字版 PDF 用 fast 策略可直接抽文本，不依赖 unstructured-inference/torch。"""
        from app.infrastructure.parsing.parser import DocumentParser

        parser = DocumentParser(TextCleaner())
        result = parser.parse_content(_build_minimal_pdf("Hello Resume"), "resume.pdf")
        assert "Hello Resume" in result


def _build_minimal_pdf(text: str) -> bytes:
    """构造含单行文本的最小合法 PDF（手写 xref，供解析集成测试用）。"""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()
    return bytes(out)
