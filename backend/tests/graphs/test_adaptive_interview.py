"""自适应面试 Agent 图单元测试：验证 StateGraph 编译和基本路由逻辑。"""

from app.domain.services.adaptive_strategy import (
    compute_strategy_update,
    should_end_interview,
)
from app.graphs.adaptive_interview import AdaptiveInterviewGraph


class TestAdaptiveInterviewGraphCompile:
    """验证 LangGraph StateGraph 编译成功。"""

    def test_graph_compiles_without_error(self) -> None:
        graph = AdaptiveInterviewGraph()
        assert graph._compiled is not None


class TestAdaptiveStrategy:
    """验证策略纯函数逻辑。"""

    def test_no_data_keeps_current(self) -> None:
        result = compute_strategy_update({}, "mid", 0, 6)
        assert result.suggested_difficulty == "mid"
        assert "尚无足够数据" in result.reason

    def test_high_scores_upgrade_difficulty(self) -> None:
        scores = {"JAVA": [8, 9], "MYSQL": [7, 8]}
        result = compute_strategy_update(scores, "mid", 4, 6)
        assert result.suggested_difficulty == "senior"

    def test_low_scores_downgrade_difficulty(self) -> None:
        scores = {"JAVA": [2, 3], "MYSQL": [3, 4]}
        result = compute_strategy_update(scores, "mid", 4, 6)
        assert result.suggested_difficulty == "junior"

    def test_mixed_scores_keep_difficulty(self) -> None:
        scores = {"JAVA": [5, 6], "MYSQL": [6, 5]}
        result = compute_strategy_update(scores, "mid", 3, 6)
        assert result.suggested_difficulty == "mid"

    def test_picks_weakest_category(self) -> None:
        scores = {"JAVA": [8, 9], "MYSQL": [3, 2], "REDIS": [7]}
        result = compute_strategy_update(scores, "mid", 3, 8)
        assert result.suggested_category == "MYSQL"

    def test_should_end_at_max_turns(self) -> None:
        assert should_end_interview(6, 6, {"JAVA": [5, 6], "MYSQL": [5, 6]}) is True

    def test_should_not_end_early(self) -> None:
        assert should_end_interview(3, 6, {"JAVA": [5]}) is False

    def test_near_end_with_coverage(self) -> None:
        assert should_end_interview(5, 6, {"JAVA": [5, 6], "MYSQL": [5, 6]}) is True
