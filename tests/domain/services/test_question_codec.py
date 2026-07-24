import json

from app.domain.entities.interview import InterviewQuestion
from app.domain.services.question_codec import deserialize_questions, serialize_questions


class TestSerialize:
    def test_uses_camel_case_keys(self) -> None:
        question = InterviewQuestion(
            question_index=0,
            question="Q",
            type="JAVA",
            category="JAVA",
            topic_summary="并发",
            is_follow_up=True,
        )
        item = json.loads(serialize_questions([question]))[0]
        assert set(item) == {
            "questionIndex",
            "question",
            "type",
            "category",
            "topicSummary",
            "userAnswer",
            "score",
            "feedback",
            "isFollowUp",
            "parentQuestionIndex",
        }
        assert item["isFollowUp"] is True

    def test_empty_list_serializes_to_empty_array(self) -> None:
        assert serialize_questions([]) == "[]"


class TestDeserialize:
    def test_defaults_is_follow_up_false_when_absent(self) -> None:
        raw = '[{"questionIndex": 0, "question": "Q", "type": "T", "category": "C"}]'
        result = deserialize_questions(raw)
        assert result[0].is_follow_up is False

    def test_empty_array_deserializes_to_empty_list(self) -> None:
        assert deserialize_questions("[]") == []


class TestRoundtrip:
    def test_optional_none_fields_roundtrip(self) -> None:
        question = InterviewQuestion(
            question_index=1,
            question="Q1",
            type="MYSQL",
            category="MYSQL",
            user_answer=None,
            parent_question_index=None,
        )
        assert deserialize_questions(serialize_questions([question])) == [question]

    def test_full_fields_roundtrip(self) -> None:
        question = InterviewQuestion(
            question_index=2,
            question="Q2",
            type="CSS",
            category="CSS",
            topic_summary="盒模型",
            user_answer="答案",
            score=88,
            feedback="不错",
            is_follow_up=True,
            parent_question_index=1,
        )
        assert deserialize_questions(serialize_questions([question])) == [question]
