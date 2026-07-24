"""出题领域服务：纯函数算法，接收/返回 dataclass，零框架依赖。

包含题量拆分、批次合并、追问拼接、兜底题生成、历史去重、prompt 段落构建。
LLM 编排不在此层（见 application/interview/question_service.py）。
"""

from app.domain.entities.interview import (
    DEFAULT_DIFFICULTY,
    MAX_FOLLOW_UP,
    MAX_HISTORICAL_QUESTIONS,
    RESUME_QUESTION_RATIO,
    HistoricalQuestion,
    InterviewQuestion,
    get_default_fallback_questions,
)
from app.domain.entities.skill import Skill, SkillCategory

_DIFFICULTY_DESCRIPTIONS: dict[str, str] = {
    "junior": "初级（侧重基础概念与常用 API）",
    "mid": "中级（侧重底层实现与性能瓶颈）",
    "senior": "高级（侧重架构选型与复杂故障排查）",
}


def split_resume_direction_counts(
    total: int,
    ratio: float = RESUME_QUESTION_RATIO,
) -> tuple[int, int]:
    """按 ratio 拆分简历题与方向题数量，余数归简历题。"""
    resume_count = round(total * ratio)
    direction_count = total - resume_count
    if direction_count < 0:
        direction_count = 0
    return resume_count, direction_count


def build_allocation_table(allocation: dict[str, int], categories: list[SkillCategory]) -> str:
    """渲染题量分配 Markdown 表格（prompt 用）。"""
    if not allocation:
        return "（无分配）"
    label_map = {c.key: c.label for c in categories}
    lines = ["| 方向 | 数量 |", "|------|------|"]
    for key, count in allocation.items():
        label = label_map.get(key, key)
        lines.append(f"| {label} | {count} |")
    return "\n".join(lines)


def build_historical_section(historical: list[HistoricalQuestion]) -> str:
    """渲染历史题 Markdown（按 type 分组，prompt 用）。"""
    if not historical:
        return "（无历史题目）"
    by_type: dict[str, list[str]] = {}
    for hq in historical:
        type_key = hq.type or "GENERAL"
        by_type.setdefault(type_key, []).append(hq.question)
    lines: list[str] = []
    for type_key, questions in by_type.items():
        lines.append(f"### {type_key}")
        for q in questions:
            lines.append(f"- {q}")
    return "\n".join(lines)


def build_difficulty_description(difficulty: str) -> str:
    """难度 -> 中文描述，未知难度回退到 mid。"""
    return _DIFFICULTY_DESCRIPTIONS.get(difficulty, _DIFFICULTY_DESCRIPTIONS[DEFAULT_DIFFICULTY])


def dedupe_historical(raw_questions: list[HistoricalQuestion]) -> list[HistoricalQuestion]:
    """按 topicSummary 标准化（strip+upper）去重，限 MAX_HISTORICAL_QUESTIONS。

    无 topicSummary 时用 question 文本兜底去重。
    """
    seen: set[str] = set()
    result: list[HistoricalQuestion] = []
    for hq in raw_questions:
        raw_key = hq.topic_summary if hq.topic_summary is not None else hq.question
        key = raw_key.strip().upper()
        if not key:
            continue
        if key not in seen:
            seen.add(key)
            result.append(hq)
        if len(result) >= MAX_HISTORICAL_QUESTIONS:
            break
    return result


def generate_fallback_questions(skill: Skill, count: int) -> list[InterviewQuestion]:
    """LLM 全失败时的兜底题生成。

    persona 非空：第 0 题用 persona 定向题，其余用硬编码兜底。
    persona 为 None：全部用硬编码兜底循环复用。
    """
    if count <= 0:
        return []
    fallbacks = get_default_fallback_questions()
    texts: list[str] = []
    if skill.persona:
        texts.append(f"请结合 {skill.persona} 方向，介绍你最有挑战的一次技术实践。")
    while len(texts) < count:
        texts.append(fallbacks[len(texts) % len(fallbacks)])
    texts = texts[:count]

    return [
        InterviewQuestion(
            question_index=i,
            question=text,
            type="GENERAL",
            category="通用",
        )
        for i, text in enumerate(texts)
    ]


def attach_follow_ups(
    main_qs: list[InterviewQuestion],
    follow_up_map: dict[int, list[str]],
    max_follow_up: int = MAX_FOLLOW_UP,
) -> list[InterviewQuestion]:
    """主问题 + 追问拼接成最终列表，追问 isFollowUp=True，parentQuestionIndex 指向重排后的主问题 index。"""
    result: list[InterviewQuestion] = []
    next_index = 0
    for main_q in main_qs:
        main_index = next_index
        result.append(
            InterviewQuestion(
                question_index=main_index,
                question=main_q.question,
                type=main_q.type,
                category=main_q.category,
                topic_summary=main_q.topic_summary,
                user_answer=main_q.user_answer,
                score=main_q.score,
                feedback=main_q.feedback,
                is_follow_up=False,
                parent_question_index=None,
            )
        )
        next_index += 1
        follow_ups = follow_up_map.get(main_q.question_index, [])[:max_follow_up]
        for fu in follow_ups:
            result.append(
                InterviewQuestion(
                    question_index=next_index,
                    question=fu,
                    type=main_q.type,
                    category=main_q.category,
                    is_follow_up=True,
                    parent_question_index=main_index,
                )
            )
            next_index += 1
    return result
