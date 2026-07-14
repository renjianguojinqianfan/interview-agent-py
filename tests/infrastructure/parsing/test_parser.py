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

    def test_parses_docx_via_unstructured(self) -> None:
        from app.infrastructure.parsing.parser import DocumentParser

        parser = DocumentParser(TextCleaner())

        fake_elements = ["DOCX paragraph 1"]

        with patch("app.infrastructure.parsing.parser._partition_docx") as mock_partition:
            mock_partition.return_value = fake_elements
            result = parser.parse_content(b"fake-docx-bytes", "doc.docx")
            assert "DOCX paragraph 1" in result

    def test_unstructured_failure_raises_business_exception(self) -> None:
        from app.api.errors import BusinessException
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
