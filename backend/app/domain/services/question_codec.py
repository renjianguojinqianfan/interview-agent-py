"""面试问题 JSON 序列化/反序列化编解码器：纯函数，零框架依赖。

在 domain InterviewQuestion 列表与 JSON 文本（camelCase 键）之间转换，
供 write 侧（PersistenceService）、read 侧（EvaluationService）与评估消费者共用。

原置于 application 层；因基础设施评估消费者需反序列化 questions_json，
infrastructure -> application 违反分层方向（AGENTS.md §4），故迁至 domain/services
（仅依赖 stdlib json + domain 实体，满足 domain 纯度）。
"""

import json

from app.domain.entities.interview import InterviewQuestion


def serialize_questions(questions: list[InterviewQuestion]) -> str:
    return json.dumps(
        [
            {
                "questionIndex": q.question_index,
                "question": q.question,
                "type": q.type,
                "category": q.category,
                "topicSummary": q.topic_summary,
                "userAnswer": q.user_answer,
                "score": q.score,
                "feedback": q.feedback,
                "isFollowUp": q.is_follow_up,
                "parentQuestionIndex": q.parent_question_index,
                "referenceAnswer": q.reference_answer,
                "keyPoints": q.key_points,
                "scoringRubric": q.scoring_rubric,
                "sourceContext": q.source_context,
            }
            for q in questions
        ],
        ensure_ascii=False,
    )


def deserialize_questions(questions_json: str) -> list[InterviewQuestion]:
    items = json.loads(questions_json)
    return [
        InterviewQuestion(
            question_index=item["questionIndex"],
            question=item["question"],
            type=item["type"],
            category=item["category"],
            topic_summary=item.get("topicSummary"),
            user_answer=item.get("userAnswer"),
            score=item.get("score"),
            feedback=item.get("feedback"),
            is_follow_up=item.get("isFollowUp", False),
            parent_question_index=item.get("parentQuestionIndex"),
            # 题库参考字段（#44）：旧 JSON 无此键，回落默认空值保持向后兼容
            reference_answer=item.get("referenceAnswer"),
            key_points=list(item.get("keyPoints") or []),
            scoring_rubric=item.get("scoringRubric"),
            source_context=item.get("sourceContext"),
        )
        for item in items
    ]
