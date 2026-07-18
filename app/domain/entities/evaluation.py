"""统一面试评估领域实体：纯 dataclass，零框架依赖。

文字面试（#9）与语音面试（#14）共用。对应 Java 的
EvaluationReport / QaRecord / BatchReportDTO / SummaryDTO。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QaRecord:
    """通用面试问答记录（文字/语音共用）。

    user_answer 为 None 表示未回答（评估时按 0 分处理）。
    """

    question_index: int
    question: str
    category: str
    user_answer: str | None


@dataclass(frozen=True)
class QuestionEvaluationItem:
    """单题 LLM 评估输出（批次内）。

    对应 Java BatchReportDTO.QuestionEvalDTO。字段名对齐 LLM 输出结构。
    """

    question_index: int
    score: int
    feedback: str
    reference_answer: str
    key_points: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BatchReport:
    """单批 LLM 评估输出。

    对应 Java BatchReportDTO。失败批次以 None 表示，由合并逻辑零分兜底。
    """

    overall_score: int
    overall_feedback: str
    strengths: list[str]
    improvements: list[str]
    question_evaluations: list[QuestionEvaluationItem]


@dataclass(frozen=True)
class QaBatch:
    """输入分批：记录批次在原 qa_records 中的起止下标与该批问答记录。"""

    start_index: int
    end_index: int
    records: list[QaRecord]


@dataclass(frozen=True)
class BatchResult:
    """批次评估结果定位：记录批次在原 qa_records 中的起止下标，用于缺失补零。

    report 为 None 表示该批 LLM 调用失败，合并时按零分兜底。
    """

    start_index: int
    end_index: int
    report: BatchReport | None


@dataclass(frozen=True)
class Summary:
    """二次汇总 LLM 输出。对应 Java SummaryDTO。"""

    overall_feedback: str
    strengths: list[str]
    improvements: list[str]

    @classmethod
    def empty(cls) -> "Summary":
        return cls(overall_feedback="", strengths=[], improvements=[])


@dataclass(frozen=True)
class CategoryScore:
    """分类得分：某 category 的平均分与题数。"""

    category: str
    score: int
    question_count: int


@dataclass(frozen=True)
class QuestionEvaluation:
    """最终报告中的逐题评估（含原始问题与回答）。"""

    question_index: int
    question: str
    category: str
    user_answer: str | None
    score: int
    feedback: str


@dataclass(frozen=True)
class ReferenceAnswer:
    """最终报告中的参考答案与核心要点。"""

    question_index: int
    question: str
    reference_answer: str
    key_points: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvaluationReport:
    """统一面试评估报告（文字/语音共用）。对应 Java EvaluationReport。

    overall_score 为已答题平均分（未回答不计入分母）；全未回答时为 0。
    """

    session_id: str
    total_questions: int
    overall_score: int
    category_scores: list[CategoryScore]
    question_details: list[QuestionEvaluation]
    overall_feedback: str
    strengths: list[str]
    improvements: list[str]
    reference_answers: list[ReferenceAnswer]
