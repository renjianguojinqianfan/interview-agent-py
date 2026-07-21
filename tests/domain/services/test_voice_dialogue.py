"""语音对话编排纯逻辑测试。"""

from app.domain.entities.voice_interview import VoiceMessage
from app.domain.services.voice_dialogue import (
    COMMIT_DEBOUNCE_MS,
    MIN_COMMIT_CHARS,
    find_latest_unanswered,
    merge_segments,
    should_commit,
    should_drop_audio,
    split_sentences,
)


class TestMergeSegments:
    def test_joins_and_strips(self) -> None:
        assert merge_segments([" 你好 ", "", "世界"]) == "你好世界"

    def test_empty(self) -> None:
        assert merge_segments([]) == ""


class TestShouldCommit:
    def test_empty_never_commits(self) -> None:
        assert should_commit("", 999999) is False

    def test_short_and_no_silence_holds(self) -> None:
        assert should_commit("短", 100) is False

    def test_length_threshold(self) -> None:
        assert should_commit("a" * MIN_COMMIT_CHARS, 0) is True

    def test_silence_debounce(self) -> None:
        assert should_commit("短", COMMIT_DEBOUNCE_MS) is True

    def test_just_below_debounce_holds(self) -> None:
        assert should_commit("短", COMMIT_DEBOUNCE_MS - 1) is False


class TestSplitSentences:
    def test_splits_on_endings_keeping_punctuation(self) -> None:
        sentences, remainder = split_sentences("你好。世界！剩")
        assert sentences == ["你好。", "世界！"]
        assert remainder == "剩"

    def test_no_ending_all_remainder(self) -> None:
        assert split_sentences("无标点") == ([], "无标点")

    def test_full_sentence_no_remainder(self) -> None:
        assert split_sentences("句子。") == (["句子。"], "")

    def test_newline_is_boundary(self) -> None:
        sentences, remainder = split_sentences("行1\n行2")
        assert sentences == ["行1"]
        assert remainder == "行2"

    def test_empty(self) -> None:
        assert split_sentences("") == ([], "")


class TestShouldDropAudio:
    def test_drops_within_mute_window(self) -> None:
        assert should_drop_audio(now_ms=100.0, mute_until_ms=500.0) is True

    def test_keeps_after_mute_window(self) -> None:
        assert should_drop_audio(now_ms=600.0, mute_until_ms=500.0) is False


def _msg(ai: str | None, user: str | None, seq: int = 1) -> VoiceMessage:
    return VoiceMessage(sequence_num=seq, phase="TECH", ai_generated_text=ai, user_recognized_text=user)


class TestFindLatestUnanswered:
    def test_empty_returns_none(self) -> None:
        assert find_latest_unanswered([]) is None

    def test_single_unanswered(self) -> None:
        assert find_latest_unanswered([_msg("Q1", None)]) == 0

    def test_returns_latest_unanswered(self) -> None:
        messages = [_msg("Q1", "A1", 1), _msg("Q2", None, 2)]
        assert find_latest_unanswered(messages) == 1

    def test_all_answered_returns_none(self) -> None:
        assert find_latest_unanswered([_msg("Q1", "A1")]) is None

    def test_message_without_question_ignored(self) -> None:
        assert find_latest_unanswered([_msg(None, None)]) is None

    def test_picks_last_when_multiple_unanswered(self) -> None:
        messages = [_msg("Q1", None, 1), _msg("Q2", None, 2)]
        assert find_latest_unanswered(messages) == 1
