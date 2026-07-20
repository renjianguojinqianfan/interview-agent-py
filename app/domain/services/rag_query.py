"""RAG 检索策略领域服务：纯 Python 决策逻辑，不依赖任何框架。

Embedding 与向量检索本身是 I/O，由 application 层执行；本模块负责检索前后的纯策略：
探测窗口归一化、动态 topK、候选合并去重、最低分过滤、无结果检测、context 组装。
"""

from dataclasses import dataclass


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


def compute_top_k(query: str, base_k: int) -> int:
    """动态 topK：过短/宽泛的问题增大候选量，较长/具体的问题减小，最少为 1。"""
    length = len(query.strip())
    if length <= 8:
        k = base_k * 2
    elif length >= 60:
        k = base_k // 2
    else:
        k = base_k
    return max(1, k)


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
