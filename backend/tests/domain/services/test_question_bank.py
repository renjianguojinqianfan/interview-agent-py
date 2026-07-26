"""question_bank 领域纯函数单测。"""

from app.domain.services.question_bank import normalize_question_key, trim_to_none


class TestNormalizeQuestionKey:
    def test_strips_whitespace_punctuation_and_case(self) -> None:
        assert normalize_question_key("什么是 Redis？") == normalize_question_key("什么是redis")

    def test_nfc_normalization(self) -> None:
        # "é" 组合形式（e + U+0301）与预组合形式（U+00E9）归一后相同
        assert normalize_question_key("caf\u00e9") == normalize_question_key("cafe\u0301")

    def test_none_and_blank_yield_empty_key(self) -> None:
        assert normalize_question_key(None) == ""
        assert normalize_question_key("  ？！ ") == ""

    def test_distinct_questions_have_distinct_keys(self) -> None:
        assert normalize_question_key("什么是缓存穿透") != normalize_question_key("什么是缓存击穿")


class TestTrimToNone:
    def test_blank_variants_become_none(self) -> None:
        assert trim_to_none(None) is None
        assert trim_to_none("") is None
        assert trim_to_none("   ") is None

    def test_trims_surrounding_whitespace(self) -> None:
        assert trim_to_none("  题干  ") == "题干"
