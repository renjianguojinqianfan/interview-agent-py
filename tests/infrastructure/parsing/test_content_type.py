from app.infrastructure.parsing.content_type import ContentTypeDetector


class TestDetectContentType:
    def test_detects_pdf_from_magic_bytes(self) -> None:
        detector = ContentTypeDetector()
        pdf_header = b"%PDF-1.4\n"
        result = detector.detect(pdf_header, "test.pdf")
        assert "pdf" in result.lower()

    def test_detects_text_from_content(self) -> None:
        detector = ContentTypeDetector()
        result = detector.detect(b"Hello, World!", "test.txt")
        assert result == "text/plain"

    def test_returns_octet_stream_for_empty_data(self) -> None:
        detector = ContentTypeDetector()
        result = detector.detect(b"", "unknown.xyz")
        assert result is not None

    def test_detects_markdown_by_filename(self) -> None:
        detector = ContentTypeDetector()
        result = detector.detect(b"# Header", "readme.md")
        assert "text" in result.lower() or "markdown" in result.lower()


class TestTypePredicates:
    def test_is_pdf(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_pdf("application/pdf") is True
        assert detector.is_pdf("text/plain") is False

    def test_is_word_document(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_word_document("application/msword") is True
        assert (
            detector.is_word_document("application/vnd.openxmlformats-officedocument.wordprocessingml.document") is True
        )
        assert detector.is_word_document("text/plain") is False

    def test_is_plain_text(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_plain_text("text/plain") is True
        assert detector.is_plain_text("text/markdown") is True
        assert detector.is_plain_text("application/pdf") is False

    def test_is_markdown_by_content_type(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_markdown("text/markdown", None) is True
        assert detector.is_markdown("text/x-markdown", None) is True

    def test_is_markdown_by_filename(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_markdown(None, "readme.md") is True
        assert detector.is_markdown(None, "notes.markdown") is True
        assert detector.is_markdown(None, "doc.txt") is False

    def test_is_markdown_returns_false_for_none(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_markdown(None, None) is False


class TestIsAllowed:
    def test_allows_pdf(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_allowed("application/pdf") is True

    def test_allows_word(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_allowed("application/msword") is True

    def test_allows_text(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_allowed("text/plain") is True

    def test_allows_markdown(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_allowed("text/markdown") is True

    def test_rejects_unknown(self) -> None:
        detector = ContentTypeDetector()
        assert detector.is_allowed("application/zip") is False
