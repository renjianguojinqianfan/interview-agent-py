from app.domain.services.rag_query import (
    RetrievedChunk,
    build_context,
    compute_top_k,
    detect_no_result,
    filter_by_min_score,
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


class TestComputeTopK:
    def test_short_query_doubles(self) -> None:
        assert compute_top_k("短", base_k=5) == 10

    def test_long_query_halves(self) -> None:
        assert compute_top_k("x" * 80, base_k=6) == 3

    def test_medium_query_base(self) -> None:
        assert compute_top_k("这是一个中等长度的问题", base_k=5) == 5

    def test_never_below_one(self) -> None:
        assert compute_top_k("x" * 80, base_k=1) == 1


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
