from app.infrastructure.parsing.text_cleaner import TextCleaner


class TestCleanTextSemantic:
    def test_removes_control_chars(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text("hello\x00\x07world")
        assert result == "helloworld"

    def test_preserves_newlines_and_tabs(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text("line1\nline2\ttabbed")
        assert "\n" in result
        assert "\t" in result

    def test_removes_image_filename_lines(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text("image123.png\nsome text\nimage456.jpeg")
        assert "image123.png" not in result
        assert "image456.jpeg" not in result
        assert "some text" in result

    def test_removes_image_urls(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text("看这个图片 https://example.com/img.png?w=100 结束")
        assert "https://example.com/img.png" not in result
        assert "看这个图片" in result

    def test_removes_file_urls(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text("file:///tmp/tika/test.pdf some text")
        assert "file:" not in result
        assert "some text" in result

    def test_removes_separator_lines(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text("line1\n---\nline2\n===\nline3\n___")
        assert "---" not in result
        assert "===" not in result
        assert "line1" in result
        assert "line2" in result


class TestCleanTextFormat:
    def test_normalizes_windows_newlines(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text("line1\r\nline2\rline3")
        assert result == "line1\nline2\nline3"

    def test_trims_trailing_spaces(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text("line1   \nline2\t\n")
        assert "   " not in result
        assert result == "line1\nline2"

    def test_compresses_multiple_blank_lines(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text("a\n\n\n\n\nb")
        assert result == "a\n\nb"

    def test_strips_leading_trailing_whitespace(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text("  \n hello \n  ")
        assert result == "hello"


class TestCleanTextEdgeCases:
    def test_empty_string_returns_empty(self) -> None:
        cleaner = TextCleaner()
        assert cleaner.clean_text("") == ""

    def test_none_returns_empty(self) -> None:
        cleaner = TextCleaner()
        assert cleaner.clean_text(None) == ""  # type: ignore[arg-type]

    def test_whitespace_only_returns_empty(self) -> None:
        cleaner = TextCleaner()
        assert cleaner.clean_text("   \n\n  \n  ") == ""


class TestCleanTextWithLimit:
    def test_truncates_to_max_length(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text_with_limit("abcdefghij", 5)
        assert result == "abcde"

    def test_no_truncation_when_under_limit(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_text_with_limit("hello", 100)
        assert result == "hello"


class TestCleanToSingleLine:
    def test_collapses_newlines_to_spaces(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_to_single_line("line1\nline2\n\nline3")
        assert result == "line1 line2 line3"

    def test_collapses_multiple_spaces(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.clean_to_single_line("a    b     c")
        assert result == "a b c"

    def test_empty_returns_empty(self) -> None:
        cleaner = TextCleaner()
        assert cleaner.clean_to_single_line("") == ""


class TestStripHtml:
    def test_removes_html_tags(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.strip_html("<p>Hello <b>World</b></p>")
        assert result == "Hello World"

    def test_decodes_common_entities(self) -> None:
        cleaner = TextCleaner()
        result = cleaner.strip_html("a&nbsp;b&amp;c&lt;d&gt;e&quot;f&apos;g")
        assert result == "a b&c<d>e\"f'g"

    def test_empty_returns_empty(self) -> None:
        cleaner = TextCleaner()
        assert cleaner.strip_html("") == ""
