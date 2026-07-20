"""RAG 检索策略领域服务：纯 Python 决策逻辑，不依赖任何框架。

Embedding 与向量检索本身是 I/O，由 application 层执行；本模块负责检索前后的纯策略：
探测窗口归一化、动态 topK、候选合并去重、最低分过滤、无结果检测、context 组装。
"""

from dataclasses import dataclass

# spec 挑战 4：动态检索参数三档阈值（按问题字符长度分段）
SHORT_QUERY_MAX = 4
MEDIUM_QUERY_MAX = 12

# spec 挑战 4：短查询放宽最低分阈值；中/长查询用 config 默认下限（None 表示沿用 config）
SHORT_QUERY_MIN_SCORE = 0.18

# spec 挑战 4：三档 topK 硬数值
_TOPK_SHORT = 20
_TOPK_MEDIUM = 12
_TOPK_LONG = 8

# Java isNoResultLike 的 5 个无信息模板子串
_NO_INFO_PATTERNS: tuple[str, ...] = (
    "没有找到相关信息",
    "未检索到相关信息",
    "信息不足",
    "超出知识库范围",
    "无法根据提供内容回答",
)


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    score: float
    kb_id: int


def normalize_probe_window(text: str, limit: int = 120) -> str:
    """归一化检索探测文本：压缩空白后截断到 limit 字符。"""
    collapsed = " ".join(text.split())
    if len(collapsed) > limit:
        return collapsed[:limit]
    return collapsed


def compute_retrieval_params(query: str) -> tuple[int, float | None]:
    """动态检索参数：按问题字符长度分档返回 (top_k, min_score)。

    spec 挑战 4：
      - 短(<=4 字符): topK=20, minScore=0.18
      - 中(<=12 字符): topK=12, minScore=None（用 config 默认）
      - 长(>12 字符): topK=8, minScore=None（用 config 默认）

    min_score=None 表示由调用方使用 config 全局默认下限。
    """
    length = len("".join(query.split()))
    if length <= SHORT_QUERY_MAX:
        return _TOPK_SHORT, SHORT_QUERY_MIN_SCORE
    if length <= MEDIUM_QUERY_MAX:
        return _TOPK_MEDIUM, None
    return _TOPK_LONG, None


def is_no_info_answer(text: str) -> bool:
    """检测 LLM 答案是否为无信息模板（Java isNoResultLike 的 5 个子串）。

    检查整段文本；流式场景由调用方在 probe buffer 累积期间增量调用。
    """
    return any(pattern in text for pattern in _NO_INFO_PATTERNS)


def merge_and_dedup(candidate_lists: list[list[RetrievedChunk]]) -> list[RetrievedChunk]:
    """合并多路检索候选：按 content 去重保留最高分，按分数降序。"""
    best: dict[str, RetrievedChunk] = {}
    for chunks in candidate_lists:
        for chunk in chunks:
            existing = best.get(chunk.content)
            if existing is None or chunk.score > existing.score:
                best[chunk.content] = chunk
    return sorted(best.values(), key=lambda c: c.score, reverse=True)


def filter_by_min_score(chunks: list[RetrievedChunk], min_score: float) -> list[RetrievedChunk]:
    return [chunk for chunk in chunks if chunk.score >= min_score]


def detect_no_result(chunks: list[RetrievedChunk]) -> bool:
    """检索结果为空视为无结果（应在 min_score 过滤之后调用）。"""
    return len(chunks) == 0


def build_context(chunks: list[RetrievedChunk], max_chars: int) -> str:
    """把候选片段组装为提示词 context，累计长度不超过 max_chars（至少保留一段）。"""
    parts: list[str] = []
    total = 0
    for index, chunk in enumerate(chunks, start=1):
        block = f"[片段{index}] {chunk.content}"
        if parts and total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)
