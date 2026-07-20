from app.domain.services.rag_query import (
    SHORT_QUERY_MIN_SCORE,
    RetrievedChunk,
    build_context,
    compute_retrieval_params,
    detect_no_result,
    filter_by_min_score,
    is_no_info_answer,
    merge_and_dedup,
    normalize_probe_window,
)


class TestNormalizeProbeWindow:
    def test_collapses_whitespace(self) -> None:
        assert normalize_probe_window("  a\n\t b   c ") == "a b c"

    def test_truncates_to_limit(self) -> None:
        text = "x" * 200
        assert len(normalize_probe_window(text, limit=120)) == 120

    def test_short_text_unchanged(self) -> None:
        assert normalize_probe_window("hello", limit=120) == "hello"


class TestComputeRetrievalParams:
    def test_short_query_tier(self) -> None:
        # spec: 短(<=4字符) topK=20/minScore=0.18
        top_k, min_score = compute_retrieval_params("索引")
        assert top_k == 20
        assert min_score == SHORT_QUERY_MIN_SCORE == 0.18

    def test_short_query_boundary_is_4_chars(self) -> None:
        assert compute_retrieval_params("abcd")[0] == 20

    def test_medium_query_tier(self) -> None:
        # spec: 中(<=12) topK=12；min_score=None 表示用 config 默认值
        top_k, min_score = compute_retrieval_params("什么是数据库索引")
        assert top_k == 12
        assert min_score is None

    def test_medium_query_boundary_is_12_chars(self) -> None:
        assert compute_retrieval_params("x" * 12)[0] == 12

    def test_long_query_tier(self) -> None:
        # spec: 长 topK=8；min_score=None
        top_k, min_score = compute_retrieval_params("x" * 60)
        assert top_k == 8
        assert min_score is None

    def test_strips_whitespace_before_tiering(self) -> None:
        # 对齐 Java：去除全部空白（含内部），4 个非空白字符仍属短查询
        assert compute_retrieval_params("  a b\tc d  ")[0] == 20


class TestIsNoInfoAnswer:
    def test_detects_no_info_found_phrase(self) -> None:
        assert is_no_info_answer("抱歉，没有找到相关信息。") is True

    def test_detects_not_retrieved_phrase(self) -> None:
        assert is_no_info_answer("未检索到相关信息。") is True

    def test_detects_info_insufficient(self) -> None:
        assert is_no_info_answer("根据知识库，信息不足以回答该问题。") is True

    def test_detects_out_of_scope(self) -> None:
        assert is_no_info_answer("该问题超出知识库范围。") is True

    def test_detects_cannot_answer_from_content(self) -> None:
        assert is_no_info_answer("无法根据提供内容回答该问题。") is True

    def test_normal_answer_not_flagged(self) -> None:
        assert is_no_info_answer("索引是一种数据结构，用于加速数据库查询。") is False

    def test_empty_answer_not_flagged(self) -> None:
        assert is_no_info_answer("") is False


class TestMergeAndDedup:
    def test_dedup_keeps_max_score_sorted_desc(self) -> None:
        a = [RetrievedChunk("A", 0.6, 1), RetrievedChunk("B", 0.9, 1)]
        b = [RetrievedChunk("A", 0.8, 2), RetrievedChunk("C", 0.5, 2)]

        merged = merge_and_dedup([a, b])

        assert [c.content for c in merged] == ["B", "A", "C"]
        a_chunk = next(c for c in merged if c.content == "A")
        assert a_chunk.score == 0.8  # 保留最高分

    def test_empty_lists(self) -> None:
        assert merge_and_dedup([[], []]) == []


class TestFilterAndNoResult:
    def test_filter_by_min_score(self) -> None:
        chunks = [RetrievedChunk("A", 0.2, 1), RetrievedChunk("B", 0.5, 1)]
        assert [c.content for c in filter_by_min_score(chunks, 0.3)] == ["B"]

    def test_detect_no_result_true_when_empty(self) -> None:
        assert detect_no_result([]) is True

    def test_detect_no_result_false_when_present(self) -> None:
        assert detect_no_result([RetrievedChunk("A", 0.9, 1)]) is False


class TestBuildContext:
    def test_numbers_and_joins(self) -> None:
        chunks = [RetrievedChunk("first", 0.9, 1), RetrievedChunk("second", 0.8, 1)]
        context = build_context(chunks, max_chars=1000)
        assert "[片段1] first" in context
        assert "[片段2] second" in context

    def test_respects_max_chars_but_keeps_first(self) -> None:
        chunks = [RetrievedChunk("x" * 50, 0.9, 1), RetrievedChunk("y" * 50, 0.8, 1)]
        context = build_context(chunks, max_chars=10)
        assert "片段1" in context
        assert "片段2" not in context
