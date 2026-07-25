"""自适应面试策略纯函数：根据候选人各维度得分计算策略调整建议。

零框架依赖，接收/返回 dataclass 或基础类型。供 interview_tools.adjust_strategy 和
adaptive_interview.py 的策略节点调用。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyUpdate:
    """策略调整建议（纯计算，无 LLM）。"""

    suggested_difficulty: str
    suggested_category: str
    reason: str


_DIFFICULTY_LEVELS = ["junior", "mid", "senior"]

# 阈值配置
_HIGH_SCORE_THRESHOLD = 7  # 平均分 >= 7 建议提升难度
_LOW_SCORE_THRESHOLD = 4  # 平均分 <= 4 建议降低难度
_WEAK_CATEGORY_THRESHOLD = 5  # 某维度平均分 < 5 视为薄弱


def compute_strategy_update(
    category_scores: dict[str, list[int]],
    current_difficulty: str,
    turn_count: int,
    max_turns: int,
) -> StrategyUpdate:
    """根据候选人各维度得分历史，计算下一轮的出题策略。

    策略规则：
    1. 若所有已答维度平均分 >= HIGH，且当前非 senior -> 提升难度
    2. 若所有已答维度平均分 <= LOW，且当前非 junior -> 降低难度
    3. 否则保持当前难度
    4. 推荐下一个出题方向：优先选得分最低的维度（薄弱点追问）
    5. 若已接近 max_turns，优先选未覆盖的维度
    """
    if not category_scores:
        return StrategyUpdate(
            suggested_difficulty=current_difficulty,
            suggested_category="通用",
            reason="尚无足够数据判断，保持当前策略",
        )

    # 计算全局平均分
    all_scores = [s for scores in category_scores.values() for s in scores]
    global_avg = sum(all_scores) / len(all_scores) if all_scores else 5

    # 防御非法 difficulty 值
    safe_difficulty = current_difficulty if current_difficulty in _DIFFICULTY_LEVELS else "mid"

    # 难度调整
    suggested_difficulty = safe_difficulty
    difficulty_reason = ""
    if global_avg >= _HIGH_SCORE_THRESHOLD and safe_difficulty != "senior":
        idx = _DIFFICULTY_LEVELS.index(safe_difficulty)
        suggested_difficulty = _DIFFICULTY_LEVELS[min(idx + 1, len(_DIFFICULTY_LEVELS) - 1)]
        difficulty_reason = f"全局平均分 {global_avg:.1f} >= {_HIGH_SCORE_THRESHOLD}，提升难度"
    elif global_avg <= _LOW_SCORE_THRESHOLD and safe_difficulty != "junior":
        idx = _DIFFICULTY_LEVELS.index(safe_difficulty)
        suggested_difficulty = _DIFFICULTY_LEVELS[max(idx - 1, 0)]
        difficulty_reason = f"全局平均分 {global_avg:.1f} <= {_LOW_SCORE_THRESHOLD}，降低难度"
    else:
        difficulty_reason = f"全局平均分 {global_avg:.1f}，保持当前难度"

    # 方向选择：优先薄弱方向
    suggested_category = _pick_next_category(category_scores, turn_count, max_turns)

    reason = f"{difficulty_reason}；下一题方向：{suggested_category}"
    return StrategyUpdate(
        suggested_difficulty=suggested_difficulty,
        suggested_category=suggested_category,
        reason=reason,
    )


def _pick_next_category(
    category_scores: dict[str, list[int]],
    turn_count: int,
    max_turns: int,
) -> str:
    """选择下一个出题方向。"""
    if not category_scores:
        return "通用"

    # 计算各维度平均分
    category_avgs: dict[str, float] = {}
    for cat, scores in category_scores.items():
        if scores:
            category_avgs[cat] = sum(scores) / len(scores)

    if not category_avgs:
        return "通用"

    # 接近结束时，选题数最少的维度（保证覆盖面）
    remaining = max_turns - turn_count
    if remaining <= 2:
        least_covered = min(category_scores.items(), key=lambda x: len(x[1]))
        return least_covered[0]

    # 优先选平均分最低的维度（薄弱追问）
    weakest = min(category_avgs.items(), key=lambda x: x[1])
    if weakest[1] < _WEAK_CATEGORY_THRESHOLD:
        return weakest[0]

    # 无明显薄弱项，选题数最少的维度（均匀覆盖）
    least_covered = min(category_scores.items(), key=lambda x: len(x[1]))
    return least_covered[0]


def should_end_interview(
    turn_count: int,
    max_turns: int,
    category_scores: dict[str, list[int]],
) -> bool:
    """判断是否应结束面试。

    结束条件：
    1. 已达最大题数
    2. 或已达 max_turns-1 且所有维度至少 2 题
    """
    if turn_count >= max_turns:
        return True
    return turn_count >= max_turns - 1 and all(len(scores) >= 2 for scores in category_scores.values())
