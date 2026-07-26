"""题库领域纯函数：题干归一化去重、组卷/容量算法与评估参考构建（AGENTS.md §4：出题策略类逻辑驻 domain/services）。

组卷与容量对齐 Java KnowledgeBaseInterviewService；评估参考对齐 Java
AnswerEvaluationService.buildQuestionReferenceContext / withQuestionReferences。
随机源（random.Random）由调用方注入，固定种子可复现（issue #44）。
"""

import unicodedata
from dataclasses import dataclass, field, replace
from random import Random

from app.domain.entities.evaluation import EvaluationReport, ReferenceAnswer
from app.domain.entities.interview import InterviewQuestion
from app.domain.errors import BusinessException, ErrorCode

MAX_FOLLOW_UP_COUNT = 5
"""每题追问上限（容量矩阵 0~5 档位）。"""

_FALLBACK_TYPE = "KNOWLEDGE_BASE"
_FALLBACK_CATEGORY = "知识库"
_FALLBACK_FOLLOW_UP_CATEGORY = "知识库追问"


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


# ==================== 组卷候选结构 ====================


@dataclass(frozen=True)
class QuestionBankFollowUp:
    """题库追问（组卷候选视角，JSON 解析由调用方完成）。"""

    question: str
    reference_answer: str | None = None
    key_points: list[str] = field(default_factory=list)
    scoring_rubric: str | None = None


@dataclass(frozen=True)
class QuestionCandidate:
    """组卷候选题源（domain 视角，对应 Java QuestionSource）。"""

    question: str
    type: str | None
    category: str | None
    topic_summary: str | None = None
    reference_answer: str | None = None
    key_points: list[str] = field(default_factory=list)
    scoring_rubric: str | None = None
    source_context: str | None = None
    follow_ups: list[QuestionBankFollowUp] = field(default_factory=list)


@dataclass(frozen=True)
class CategoryOption:
    """容量预检：某方向的可用题数。"""

    category: str
    available_question_count: int


@dataclass(frozen=True)
class FollowUpOption:
    """容量预检：某追问档位的可用主问题数与可行性。"""

    follow_up_count: int
    available_question_count: int
    selectable: bool


# ==================== 组卷 ====================


def assemble_interview_questions(
    candidates: list[QuestionCandidate],
    main_count: int,
    follow_up_count: int,
    rng: Random,
    difficulty: str,
    category: str | None = None,
) -> list[InterviewQuestion]:
    """从候选题随机组卷：主题洗牌取 main_count + 每题 Fisher-Yates 抽 follow_up_count 个追问。

    候选（追问池 >= follow_up_count）不足时抛 INTERVIEW_QUESTION_INSUFFICIENT，
    消息含方向/难度/追问约束明细（对齐 Java buildInsufficientMessage）。
    difficulty/category 仅用于不足消息拼装，过滤由调用方查询完成。
    """
    eligible = [c for c in candidates if len(c.follow_ups) >= follow_up_count]
    if len(eligible) < main_count:
        raise BusinessException(
            ErrorCode.INTERVIEW_QUESTION_INSUFFICIENT,
            _build_insufficient_message(main_count, len(eligible), category, difficulty, follow_up_count),
        )

    shuffled = list(eligible)
    rng.shuffle(shuffled)

    questions: list[InterviewQuestion] = []
    for candidate in shuffled[:main_count]:
        main_index = len(questions)
        questions.append(
            InterviewQuestion(
                question_index=main_index,
                question=candidate.question,
                type=_default_string(candidate.type, _FALLBACK_TYPE),
                category=_default_string(candidate.category, _FALLBACK_CATEGORY),
                topic_summary=candidate.topic_summary,
                reference_answer=candidate.reference_answer,
                key_points=list(candidate.key_points),
                scoring_rubric=candidate.scoring_rubric,
                source_context=candidate.source_context,
            )
        )
        for follow_up in _pick_follow_ups(candidate.follow_ups, follow_up_count, rng):
            questions.append(
                InterviewQuestion(
                    question_index=len(questions),
                    question=follow_up.question,
                    type=_default_string(candidate.type, _FALLBACK_TYPE),
                    category=_default_string(candidate.category, _FALLBACK_FOLLOW_UP_CATEGORY),
                    topic_summary=candidate.topic_summary,
                    is_follow_up=True,
                    parent_question_index=main_index,
                    reference_answer=follow_up.reference_answer,
                    key_points=list(follow_up.key_points),
                    scoring_rubric=follow_up.scoring_rubric,
                    source_context=candidate.source_context,
                )
            )
    return questions


def _pick_follow_ups(
    pool: list[QuestionBankFollowUp],
    count: int,
    rng: Random,
) -> list[QuestionBankFollowUp]:
    """追问池随机抽严格 count 个（Fisher-Yates 局部洗牌，不改动原列表）。

    调用方已按池容量过滤，此处不足属组装中途池变化，同样拒绝（对齐 Java pickFollowUps）。
    """
    if count <= 0:
        return []
    if len(pool) < count:
        raise BusinessException(
            ErrorCode.INTERVIEW_QUESTION_INSUFFICIENT,
            f"追问池在组装面试时发生变化，无法严格抽取 {count} 个追问",
        )
    if len(pool) == count:
        return list(pool)
    copy = list(pool)
    for i in range(count):
        j = rng.randrange(i, len(copy))
        copy[i], copy[j] = copy[j], copy[i]
    return copy[:count]


def _build_insufficient_message(
    required_count: int,
    available_count: int,
    category: str | None,
    difficulty: str,
    follow_up_count: int,
) -> str:
    direction = category if category is not None else "全部方向"
    return (
        f"需要 {required_count} 道主问题，但只有 {available_count} 道同时满足："
        f"方向={direction}、难度={difficulty}、每题至少 {follow_up_count} 个追问"
    )


def _default_string(value: str | None, fallback: str) -> str:
    if value is None or not value.strip():
        return fallback
    return value


# ==================== 容量预检 ====================


def calculate_interview_capacity(
    all_candidates: list[QuestionCandidate],
    category: str | None,
    main_count: int,
    max_follow_up: int = MAX_FOLLOW_UP_COUNT,
) -> tuple[list[CategoryOption], list[FollowUpOption]]:
    """容量预检：方向计数（全量，count desc + category asc）+ 0~max 追问档位可行性矩阵。

    追问档位基于 category 过滤后的 scoped 候选；selectable = main_count > 0 且
    该档位可用主问题数 >= main_count（对齐 Java getCapacity）。
    """
    counts: dict[str, int] = {}
    for candidate in all_candidates:
        name = trim_to_none(candidate.category)
        if name is not None:
            counts[name] = counts.get(name, 0) + 1
    categories = [
        CategoryOption(category=name, available_question_count=count)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    scoped = [c for c in all_candidates if category is None or c.category == category]
    follow_up_options = []
    for count in range(max_follow_up + 1):
        available = sum(1 for c in scoped if len(c.follow_ups) >= count)
        follow_up_options.append(
            FollowUpOption(
                follow_up_count=count,
                available_question_count=available,
                selectable=main_count > 0 and available >= main_count,
            )
        )
    return categories, follow_up_options


# ==================== 评估参考 ====================


def build_question_reference_context(questions: list[InterviewQuestion]) -> str:
    """从随题下发的题库参考拼接评估参考上下文（对齐 Java buildQuestionReferenceContext）。

    无任何参考时返回空串，调用方回落既有行为（普通面试不变）。
    """
    sections: list[str] = []
    for question in questions:
        if not _has_question_reference(question):
            continue
        lines = [f"问题{question.question_index + 1}: {question.question}"]
        answer = trim_to_none(question.reference_answer)
        if answer is not None:
            lines.append(f"参考答案: {answer}")
        if question.key_points:
            lines.append(f"评分要点: {'、'.join(question.key_points)}")
        rubric = trim_to_none(question.scoring_rubric)
        if rubric is not None:
            lines.append(f"评分规则: {rubric}")
        sections.append("\n".join(lines))
    if not sections:
        return ""
    return "\n\n".join(sections) + "\n"


def apply_question_references(
    report: EvaluationReport,
    questions: list[InterviewQuestion],
) -> EvaluationReport:
    """用题库标准答案覆盖报告中已存在的 referenceAnswers 项（对齐 Java withQuestionReferences）。

    仅当对应题目携非空 reference_answer 时覆盖答案与要点，保留原 questionIndex/question；
    无题库参考的项保留 LLM 产出。
    """
    question_map = {q.question_index: q for q in questions}
    references: list[ReferenceAnswer] = []
    changed = False
    for reference in report.reference_answers:
        question = question_map.get(reference.question_index)
        bank_answer = question.reference_answer if question is not None else None
        if question is None or bank_answer is None or not bank_answer.strip():
            references.append(reference)
            continue
        references.append(
            ReferenceAnswer(
                question_index=reference.question_index,
                question=reference.question,
                reference_answer=bank_answer,
                key_points=list(question.key_points),
            )
        )
        changed = True
    if not changed:
        return report
    return replace(report, reference_answers=references)


def _has_question_reference(question: InterviewQuestion) -> bool:
    return (
        trim_to_none(question.reference_answer) is not None
        or bool(question.key_points)
        or trim_to_none(question.scoring_rubric) is not None
    )
