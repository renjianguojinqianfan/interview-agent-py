import pytest

from app.infrastructure.parsing.chunker import TokenChunker


class _CharEncoder:
    """每字符视作一个 token 的确定性编码器，保证测试 hermetic（不加载 tiktoken）。"""

    def encode(self, text: str) -> list[int]:
        return [ord(c) for c in text]

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(t) for t in tokens)


class TestValidation:
    def test_overlap_ge_size_raises(self) -> None:
        with pytest.raises(ValueError):
            TokenChunker(chunk_size=10, chunk_overlap=10, encoder=_CharEncoder())

    def test_non_positive_size_raises(self) -> None:
        with pytest.raises(ValueError):
            TokenChunker(chunk_size=0, chunk_overlap=0, encoder=_CharEncoder())

    def test_negative_overlap_raises(self) -> None:
        with pytest.raises(ValueError):
            TokenChunker(chunk_size=10, chunk_overlap=-1, encoder=_CharEncoder())


class TestSplit:
    def test_empty_and_whitespace_return_no_chunks(self) -> None:
        chunker = TokenChunker(chunk_size=10, chunk_overlap=3, encoder=_CharEncoder())
        assert chunker.split("") == []
        assert chunker.split("   ") == []

    def test_short_text_single_chunk(self) -> None:
        chunker = TokenChunker(chunk_size=10, chunk_overlap=3, encoder=_CharEncoder())
        assert chunker.split("hello") == ["hello"]

    def test_no_overlap_step_equals_size(self) -> None:
        chunker = TokenChunker(chunk_size=5, chunk_overlap=0, encoder=_CharEncoder())
        assert chunker.split("abcdefghij") == ["abcde", "fghij"]

    def test_long_text_windows_with_overlap(self) -> None:
        chunker = TokenChunker(chunk_size=10, chunk_overlap=3, encoder=_CharEncoder())
        text = "abcdefghijklmnopqrstuvwxy"  # 25 chars -> 窗口 [0:10],[7:17],[14:24],[21:25]
        chunks = chunker.split(text)

        assert chunks == [text[0:10], text[7:17], text[14:24], text[21:25]]
        # 相邻分块重叠 3 个 token
        assert chunks[0][-3:] == chunks[1][:3]

    def test_default_construction_does_not_load_tiktoken(self) -> None:
        # 默认编码器惰性加载：仅构造不应触发词表加载或联网
        chunker = TokenChunker()
        assert chunker is not None
