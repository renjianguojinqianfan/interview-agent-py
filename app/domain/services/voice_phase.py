"""语音面试阶段切换领域服务：纯函数，零框架依赖。

三规则（附录 F / migration-plan 7B.8）：
- 规则1 maxDuration：达到最大时长 -> 强制切换
- 规则2 maxQuestions：达到最大题数 -> 建议切换
- 规则3 suggestedDuration + minQuestions：达到建议时长且满足最小题数 -> 建议切换
阶段顺序 INTRO -> TECH -> PROJECT -> HR -> COMPLETED，跳过未启用阶段。
"""

from app.domain.entities.voice_interview import PHASE_CONFIGS, InterviewPhase

_PHASE_ORDER: tuple[InterviewPhase, ...] = (
    InterviewPhase.INTRO,
    InterviewPhase.TECH,
    InterviewPhase.PROJECT,
    InterviewPhase.HR,
)


def should_transition_to_next_phase(phase: InterviewPhase, elapsed_seconds: float, question_count: int) -> bool:
    """依据三规则判定当前阶段是否应切换到下一阶段。终态/未知阶段恒 False。"""
    config = PHASE_CONFIGS.get(phase)
    if config is None:
        return False
    if elapsed_seconds >= config.max_duration_seconds:
        return True
    if question_count >= config.max_questions:
        return True
    return elapsed_seconds >= config.suggested_duration_seconds and question_count >= config.min_questions


def next_phase(current: InterviewPhase, enabled: frozenset[InterviewPhase]) -> InterviewPhase:
    """返回 current 之后第一个启用的阶段；无则返回 COMPLETED。"""
    try:
        start = _PHASE_ORDER.index(current)
    except ValueError:
        return InterviewPhase.COMPLETED
    for phase in _PHASE_ORDER[start + 1 :]:
        if phase in enabled:
            return phase
    return InterviewPhase.COMPLETED
