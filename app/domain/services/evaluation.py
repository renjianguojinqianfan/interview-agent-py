"""统一评估领域服务：纯函数算法，零框架依赖。

对照 Java UnifiedEvaluationService 的合并/汇总/报告构建逻辑。
LLM 调用编排由 graphs/evaluation.py 子图负责；本模块只做确定性数据加工，
接收/返回 domain dataclass，可被 #9 文字评估与 #14 语音评估复用。
"""

from app.domain.entities.evaluation import (
    BatchResult,
    CategoryScore,
    EvaluationReport,
    QaBatch,
    QaRecord,
    QuestionEvaluation,
    QuestionEvaluationItem,
    ReferenceAnswer,
    Summary,
)
from app.domain.entities.interview import InterviewQuestion

MAX_RESUME_CHARS = 3000
"""简历摘要截断上限（约 1500~2000 tokens），避免 token 消耗过大。"""

MAX_REFERENCE_CONTEXT_CHARS = 6000
"""参考答案基线截断上限。"""

EVALUATION_BATCH_SIZE = 8
"""单批评估题数。"""

MAX_MERGED_LIST_ITEMS = 8
"""合并后 strengths/improvements 最大条数。"""

MAX_QUESTION_HIGHLIGHTS = 20
"""二次汇总 prompt 中题目高亮最大条数。"""

_QUESTION_TRUNCATE = 50
_FEEDBACK_TRUNCATE = 80

_NO_EVAL_FEEDBACK = "该题未成功生成评估结果，系统按 0 分处理。"
_NO_FEEDBACK = "该题未成功生成评估反馈。"
_DEFAULT_OVERALL_FEEDBACK = "本次面试已完成分批评估，但未生成有效综合评语。"


def truncate_resume(text: str | None, limit: int = MAX_RESUME_CHARS) -> str:
    """简历摘要超长截断，保留前 limit 字符并追加截断标记。"""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(简历内容过长，已截断)"


def truncate_reference(text: str | None, limit: int = MAX_REFERENCE_CONTEXT_CHARS) -> str:
    """参考答案基线超长截断；None 返回空串。"""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(参考基线过长，已截断)"


def build_qa_records_text(batch: list[QaRecord]) -> str:
    """构建 prompt 用的问答记录文本（与 Java buildQARecords 一致）。"""
    parts: list[str] = []
    for q in batch:
        answer = q.user_answer if q.user_answer else "(未回答)"
        parts.append(f"问题{q.question_index + 1} [{q.category}]: {q.question}\n回答: {answer}\n")
    return "\n".join(parts)


def overlay_answers(
    questions: list[InterviewQuestion],
    answer_map: dict[int, str],
) -> list[InterviewQuestion]:
    """按 question_index 将 answers 表的 user_answer 叠加到 questions_json 反序列化结果。

    answers 表是 user_answer 的权威来源（DB questions_json 的 userAnswer 恒为 None）。
    越界或缺失的 index 保持原样（user_answer=None）。
    """
    result = list(questions)
    for idx, answer in answer_map.items():
        if 0 <= idx < len(result):
            result[idx] = result[idx].with_answer(answer)
    return result


def build_qa_records(questions: list[InterviewQuestion]) -> list[QaRecord]:
    """将 domain 问题列表映射为 QaRecord 列表（保留 user_answer，可能为 None）。"""
    return [
        QaRecord(
            question_index=q.question_index,
            question=q.question,
            category=q.category,
            user_answer=q.user_answer,
        )
        for q in questions
    ]


def split_batches(qa_records: list[QaRecord], batch_size: int = EVALUATION_BATCH_SIZE) -> list[QaBatch]:
    """将问答记录按 batch_size 分批，记录每批在原列表中的起止下标。"""
    if not qa_records:
        return []
    size = max(1, batch_size)
    batches: list[QaBatch] = []
    for start in range(0, len(qa_records), size):
        end = min(start + size, len(qa_records))
        batches.append(QaBatch(start_index=start, end_index=end, records=list(qa_records[start:end])))
    return batches


def merge_question_evaluations(batch_results: list[BatchResult]) -> list[QuestionEvaluationItem]:
    """合并各批次逐题评估，缺失项补零分（与 Java mergeQuestionEvaluations 一致）。"""
    merged: list[QuestionEvaluationItem] = []
    for result in batch_results:
        expected = result.end_index - result.start_index
        current = result.report.question_evaluations if result.report else []
        for i in range(expected):
            if i < len(current):
                merged.append(current[i])
            else:
                merged.append(
                    QuestionEvaluationItem(
                        question_index=result.start_index + i,
                        score=0,
                        feedback=_NO_EVAL_FEEDBACK,
                        reference_answer="",
                        key_points=[],
                    )
                )
    return merged


def merge_overall_feedback(batch_results: list[BatchResult]) -> str:
    """拼接各批次非空评语；全空时返回默认提示。"""
    feedback = "\n\n".join(
        r.report.overall_feedback
        for r in batch_results
        if r.report and r.report.overall_feedback and r.report.overall_feedback.strip()
    )
    return feedback if feedback else _DEFAULT_OVERALL_FEEDBACK


def merge_list_items(batch_results: list[BatchResult], strengths_mode: bool) -> list[str]:
    """合并 strengths/improvements：去重保序、限 MAX_MERGED_LIST_ITEMS 条（与 Java 一致）。"""
    seen: set[str] = set()
    merged: list[str] = []
    for result in batch_results:
        report = result.report
        if report is None:
            continue
        items = report.strengths if strengths_mode else report.improvements
        if not items:
            continue
        for item in items:
            if not item or not item.strip():
                continue
            cleaned = item.strip()
            if cleaned not in seen:
                seen.add(cleaned)
                merged.append(cleaned)
                if len(merged) >= MAX_MERGED_LIST_ITEMS:
                    return merged
    return merged


def build_category_summary(
    qa_records: list[QaRecord],
    evaluations: list[QuestionEvaluationItem],
) -> str:
    """构建二次汇总 prompt 用的分类得分概览（仅已答题计入平均分）。"""
    scores_by_category: dict[str, list[int]] = {}
    for i, q in enumerate(qa_records):
        if not q.user_answer:
            continue
        score = evaluations[i].score if i < len(evaluations) else 0
        scores_by_category.setdefault(q.category, []).append(score)
    lines = [
        f"- {cat}: 平均分 {int(sum(scores) / len(scores))}, 题数 {len(scores)}"
        for cat, scores in sorted(scores_by_category.items())
    ]
    return "\n".join(lines)


def build_question_highlights(
    qa_records: list[QaRecord],
    evaluations: list[QuestionEvaluationItem],
) -> str:
    """构建二次汇总 prompt 用的题目高亮（截断长问题/反馈，限 MAX_QUESTION_HIGHLIGHTS 条）。"""
    highlights: list[str] = []
    for i, q in enumerate(qa_records):
        if len(highlights) >= MAX_QUESTION_HIGHLIGHTS:
            break
        eval_item = evaluations[i] if i < len(evaluations) else None
        score = eval_item.score if eval_item else 0
        feedback = eval_item.feedback if eval_item and eval_item.feedback else ""
        short_q = q.question[:_QUESTION_TRUNCATE] + "..." if len(q.question) > _QUESTION_TRUNCATE else q.question
        short_f = feedback[:_FEEDBACK_TRUNCATE] + "..." if len(feedback) > _FEEDBACK_TRUNCATE else feedback
        highlights.append(f"- Q{q.question_index + 1} | {short_q} | 分数:{score} | 反馈:{short_f}")
    return "\n".join(highlights)


def build_report(
    session_id: str,
    qa_records: list[QaRecord],
    evaluations: list[QuestionEvaluationItem],
    summary: Summary,
) -> EvaluationReport:
    """组装最终评估报告（与 Java buildReport 一致）。

    overall_score = 已答题平均分（未回答不计入分母）；全未回答时为 0。
    """
    question_details: list[QuestionEvaluation] = []
    reference_answers: list[ReferenceAnswer] = []
    category_scores_map: dict[str, list[int]] = {}

    for i, q in enumerate(qa_records):
        eval_item = evaluations[i] if i < len(evaluations) else None
        has_answer = bool(q.user_answer)
        score = eval_item.score if (has_answer and eval_item) else 0
        feedback = eval_item.feedback if (eval_item and eval_item.feedback) else _NO_FEEDBACK
        ref_answer = eval_item.reference_answer if (eval_item and eval_item.reference_answer) else ""
        key_points = eval_item.key_points if eval_item else []

        question_details.append(
            QuestionEvaluation(
                question_index=q.question_index,
                question=q.question,
                category=q.category,
                user_answer=q.user_answer,
                score=score,
                feedback=feedback,
            )
        )
        reference_answers.append(
            ReferenceAnswer(
                question_index=q.question_index,
                question=q.question,
                reference_answer=ref_answer,
                key_points=list(key_points),
            )
        )
        # 分类平均分仅计已答题（未回答不计入分母，与 overall_score / build_category_summary 一致）
        if has_answer:
            category_scores_map.setdefault(q.category, []).append(score)

    category_scores = [
        CategoryScore(
            category=cat,
            score=int(sum(scores) / len(scores)),
            question_count=len(scores),
        )
        for cat, scores in category_scores_map.items()
    ]

    answered_count = sum(1 for q in qa_records if q.user_answer)
    overall_score = int(sum(d.score for d in question_details) / answered_count) if answered_count else 0

    return EvaluationReport(
        session_id=session_id,
        total_questions=len(qa_records),
        overall_score=overall_score,
        category_scores=category_scores,
        question_details=question_details,
        overall_feedback=summary.overall_feedback,
        strengths=list(summary.strengths),
        improvements=list(summary.improvements),
        reference_answers=reference_answers,
    )
