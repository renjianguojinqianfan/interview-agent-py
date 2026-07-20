from typing import Any, Protocol

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_ENCODING = "cl100k_base"


class TokenEncoder(Protocol):
    """Token 编解码协议，便于测试注入轻量实现，避免真实加载 tiktoken 词表。"""

    def encode(self, text: str) -> list[int]: ...

    def decode(self, tokens: list[int]) -> str: ...


class _TiktokenEncoder:
    """基于 tiktoken 的默认编码器，惰性加载词表（构造/导入时不触发下载）。"""

    def __init__(self, encoding_name: str = DEFAULT_ENCODING) -> None:
        self._encoding_name = encoding_name
        self._encoding: Any = None

    def _get_encoding(self) -> Any:
        if self._encoding is None:
            import tiktoken

            self._encoding = tiktoken.get_encoding(self._encoding_name)
        return self._encoding

    def encode(self, text: str) -> list[int]:
        tokens: list[int] = list(self._get_encoding().encode(text))
        return tokens

    def decode(self, tokens: list[int]) -> str:
        return str(self._get_encoding().decode(tokens))


class TokenChunker:
    """按 token 数把长文本切分为带重叠的分块，用于知识库向量化。"""

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        encoder: TokenEncoder | None = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须为正整数")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap 不能为负数")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._encoder: TokenEncoder = encoder if encoder is not None else _TiktokenEncoder()

    def split(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        tokens = self._encoder.encode(text)
        if not tokens:
            return []

        step = self._chunk_size - self._chunk_overlap
        total = len(tokens)
        chunks: list[str] = []
        start = 0
        while start < total:
            window = tokens[start : start + self._chunk_size]
            chunk = self._encoder.decode(window)
            if chunk.strip():
                chunks.append(chunk)
            if start + self._chunk_size >= total:
                break
            start += step
        return chunks
