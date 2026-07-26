"""题库领域纯函数：题干归一化去重键与文本清理（AGENTS.md §4：出题策略类逻辑驻 domain/services）。

#44 组卷/容量算法将扩展本模块。
"""

import unicodedata


def normalize_question_key(question: str | None) -> str:
    """题干归一化去重键：NFC + 小写 + 仅保留字母数字（对齐 Java normalizeQuestionKey）。

    使「什么是 Redis？」与「什么是redis」归一为同一 key，用于生成批次内去重。
    """
    if question is None:
        return ""
    normalized = unicodedata.normalize("NFC", question).lower()
    return "".join(ch for ch in normalized if ch.isalnum())


def trim_to_none(value: str | None) -> str | None:
    """空白归一为 None，其余 trim（对齐 Java trimToNull）。"""
    if value is None or not value.strip():
        return None
    return value.strip()
