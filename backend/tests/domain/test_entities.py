from app.domain.entities.evaluation import Summary
from app.domain.entities.interview import InterviewQuestion, get_default_fallback_questions
from app.domain.entities.voice_interview import PHASE_CONFIGS, InterviewPhase


class TestInterviewQuestionWithAnswer:
    def test_returns_new_instance_with_answer(self) -> None:
        question = InterviewQuestion(question_index=0, question="Q", type="JAVA", category="JAVA")
        answered = question.with_answer("我的回答")
        assert answered is not question
        assert answered.user_answer == "我的回答"

    def test_does_not_mutate_original(self) -> None:
        question = InterviewQuestion(question_index=0, question="Q", type="JAVA", category="JAVA")
        question.with_answer("答")
        assert question.user_answer is None

    def test_preserves_other_fields(self) -> None:
        question = InterviewQuestion(
            question_index=3,
            question="Q",
            type="MYSQL",
            category="MYSQL",
            topic_summary="索引",
            is_follow_up=True,
            parent_question_index=1,
        )
        answered = question.with_answer("答")
        assert answered.question_index == 3
        assert answered.topic_summary == "索引"
        assert answered.is_follow_up is True
        assert answered.parent_question_index == 1


class TestSummaryEmpty:
    def test_empty_has_blank_feedback_and_empty_lists(self) -> None:
        summary = Summary.empty()
        assert summary.overall_feedback == ""
        assert summary.strengths == []
        assert summary.improvements == []


class TestPhaseConfigs:
    def test_covers_all_active_phases(self) -> None:
        # COMPLETED 为终态，无时长/题数配置，故不在 PHASE_CONFIGS 内
        assert set(PHASE_CONFIGS) == {
            InterviewPhase.INTRO,
            InterviewPhase.TECH,
            InterviewPhase.PROJECT,
            InterviewPhase.HR,
        }
        assert InterviewPhase.COMPLETED not in PHASE_CONFIGS

    def test_each_config_phase_matches_key(self) -> None:
        for phase, config in PHASE_CONFIGS.items():
            assert config.phase == phase


class TestDefaultFallbackQuestions:
    def test_returns_non_empty_tuple(self) -> None:
        questions = get_default_fallback_questions()
        assert isinstance(questions, tuple)
        assert len(questions) == 5

    def test_is_stable_across_calls(self) -> None:
        assert get_default_fallback_questions() == get_default_fallback_questions()
