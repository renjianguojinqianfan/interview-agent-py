"""语音面试阶段切换纯逻辑测试。"""

from app.domain.entities.voice_interview import InterviewPhase
from app.domain.services.voice_phase import next_phase, should_transition_to_next_phase

_ALL = frozenset({InterviewPhase.INTRO, InterviewPhase.TECH, InterviewPhase.PROJECT, InterviewPhase.HR})


class TestShouldTransition:
    def test_max_duration_forces(self) -> None:
        # TECH max_duration=15min
        assert should_transition_to_next_phase(InterviewPhase.TECH, 15 * 60, 0) is True

    def test_max_questions_suggests(self) -> None:
        # TECH max_questions=8
        assert should_transition_to_next_phase(InterviewPhase.TECH, 0, 8) is True

    def test_suggested_duration_plus_min_questions(self) -> None:
        # TECH suggested=10min, min_questions=3
        assert should_transition_to_next_phase(InterviewPhase.TECH, 10 * 60, 3) is True

    def test_holds_below_min_questions(self) -> None:
        assert should_transition_to_next_phase(InterviewPhase.TECH, 10 * 60, 2) is False

    def test_holds_below_suggested_duration(self) -> None:
        assert should_transition_to_next_phase(InterviewPhase.TECH, 5 * 60, 5) is False

    def test_completed_phase_never_transitions(self) -> None:
        assert should_transition_to_next_phase(InterviewPhase.COMPLETED, 999999, 999) is False


class TestNextPhase:
    def test_intro_to_tech(self) -> None:
        assert next_phase(InterviewPhase.INTRO, _ALL) == InterviewPhase.TECH

    def test_skips_disabled_phase(self) -> None:
        enabled = frozenset({InterviewPhase.INTRO, InterviewPhase.PROJECT, InterviewPhase.HR})
        assert next_phase(InterviewPhase.INTRO, enabled) == InterviewPhase.PROJECT

    def test_hr_to_completed(self) -> None:
        assert next_phase(InterviewPhase.HR, _ALL) == InterviewPhase.COMPLETED

    def test_only_intro_enabled_to_completed(self) -> None:
        assert next_phase(InterviewPhase.INTRO, frozenset({InterviewPhase.INTRO})) == InterviewPhase.COMPLETED

    def test_completed_stays_completed(self) -> None:
        assert next_phase(InterviewPhase.COMPLETED, _ALL) == InterviewPhase.COMPLETED
