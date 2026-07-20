"""面试问题 JSON 序列化/反序列化编解码器。

从 InterviewPersistenceService 提取为独立模块，消除 read 侧（EvaluationService）
对 write 侧（PersistenceService）的内部依赖。
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
        )
        for item in items
    ]
