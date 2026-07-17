"""技能领域服务：纯函数算法，接收/返回 dataclass，零框架依赖。

包含题量分配（allocation）、参考文件清单构建、category 清洗、
自定义 Skill 匹配纠正。LLM 编排不在此层（见 application/skill/service.py）。
"""

import logging
import re

from app.domain.entities.skill import (
    CategoryPriority,
    JdCategory,
    RefMapping,
    Skill,
    SkillCategory,
)

CUSTOM_SKILL_ID = "custom"
MIN_JD_LENGTH = 50
MAX_CATEGORY_KEY_LENGTH = 50
MAX_CATEGORY_LABEL_LENGTH = 50

_KEY_SANITIZE_PATTERN = re.compile(r"[^A-Z0-9_]")
_NEWLINE_PATTERN = re.compile(r"[\r\n]+")

logger = logging.getLogger(__name__)


def calculate_allocation(categories: list[SkillCategory], total_questions: int) -> dict[str, int]:
    """三阶段题量分配：ALWAYS_ONE 保底 -> 全覆盖 -> CORE 优先轮转。"""
    always_one_cats = [c for c in categories if c.priority == CategoryPriority.ALWAYS_ONE]
    core_cats = [c for c in categories if c.priority == CategoryPriority.CORE]
    normal_cats = [
        c for c in categories if c.priority != CategoryPriority.ALWAYS_ONE and c.priority != CategoryPriority.CORE
    ]

    allocation: dict[str, int] = {}
    remaining = total_questions

    for cat in always_one_cats:
        if remaining > 0:
            allocation[cat.key] = 1
            remaining -= 1

    for cat in core_cats:
        if remaining > 0:
            allocation[cat.key] = 1
            remaining -= 1
    for cat in normal_cats:
        if remaining > 0:
            allocation[cat.key] = 1
            remaining -= 1

    while remaining > 0 and (core_cats or normal_cats):
        for cat in core_cats:
            if remaining <= 0:
                break
            allocation[cat.key] = allocation.get(cat.key, 0) + 1
            remaining -= 1
        for cat in normal_cats:
            if remaining <= 0:
                break
            allocation[cat.key] = allocation.get(cat.key, 0) + 1
            remaining -= 1

    for cat in core_cats:
        allocation.setdefault(cat.key, 0)
    for cat in normal_cats:
        allocation.setdefault(cat.key, 0)

    return allocation


def sanitize_category_key(key: str | None) -> str:
    """清洗 category key：截断、非法字符替换为下划线、转大写、首字符须字母。"""
    if key is None or not key.strip():
        return "UNKNOWN"
    trimmed = key.strip()
    if len(trimmed) > MAX_CATEGORY_KEY_LENGTH:
        trimmed = trimmed[:MAX_CATEGORY_KEY_LENGTH]
    upper = _KEY_SANITIZE_PATTERN.sub("_", trimmed.upper())
    if not upper:
        return "UNKNOWN"
    if not upper[0].isalpha():
        upper = "CAT_" + upper
    return upper


def sanitize_category_label(label: str | None) -> str:
    """清洗 category label：截断、移除换行。"""
    if label is None or not label.strip():
        return "未命名"
    trimmed = _NEWLINE_PATTERN.sub(" ", label.strip())
    if len(trimmed) > MAX_CATEGORY_LABEL_LENGTH:
        trimmed = trimmed[:MAX_CATEGORY_LABEL_LENGTH]
    return trimmed


def build_reference_file_list(skills: list[Skill]) -> str:
    """构建 JD 解析 prompt 用的参考文件清单 Markdown 表格（按文件名去重）。"""
    ref_descriptions: dict[str, str] = {}
    for skill in skills:
        for cat in skill.categories:
            if cat.ref:
                scope = "shared" if cat.shared else "skill-local"
                ref_descriptions.setdefault(
                    cat.ref,
                    f"| {cat.ref} | {scope} | {skill.name} | {cat.label} |\n",
                )

    if not ref_descriptions:
        return "（无可用参考文件）"

    builder = "| 文件名 | 范围 | 来源 Skill | 覆盖内容 |\n"
    builder += "|--------|------|-------------|----------|\n"
    for row in ref_descriptions.values():
        builder += row
    return builder


def build_category_ref_index(skills: list[Skill]) -> dict[str, RefMapping]:
    """构建 category key -> RefMapping 映射，首个出现的 skill 优先，分歧时告警。"""
    index: dict[str, RefMapping] = {}
    for skill in skills:
        for cat in skill.categories:
            if cat.ref and cat.key:
                existing = index.get(cat.key)
                if existing is None:
                    index[cat.key] = RefMapping(ref=cat.ref, shared=cat.shared, source_skill_id=skill.id)
                elif existing.ref != cat.ref or existing.shared != cat.shared:
                    logger.warning(
                        "category key %s 在多个技能中存在不同 ref/shared，保留 %s(ref=%s) 忽略 %s(ref=%s)",
                        cat.key,
                        existing.source_skill_id,
                        existing.ref,
                        skill.id,
                        cat.ref,
                    )
    return index


def build_custom_skill(
    custom_categories: list[JdCategory],
    category_ref_index: dict[str, RefMapping],
    jd_text: str,
) -> Skill:
    """从 JD 解析结果构建自定义 Skill，按本地索引纠正 ref/shared。"""
    categories: list[SkillCategory] = []
    for cat in custom_categories:
        if not cat.key or not cat.label:
            continue
        safe_key = sanitize_category_key(cat.key)
        safe_label = sanitize_category_label(cat.label)
        ref_mapping = category_ref_index.get(safe_key)
        if ref_mapping is not None:
            categories.append(
                SkillCategory(
                    key=safe_key,
                    label=safe_label,
                    priority=cat.priority,
                    ref=ref_mapping.ref,
                    shared=ref_mapping.shared,
                )
            )
        else:
            categories.append(
                SkillCategory(
                    key=safe_key,
                    label=safe_label,
                    priority=cat.priority,
                    ref=cat.ref,
                    shared=bool(cat.shared),
                )
            )

    return Skill(
        id=CUSTOM_SKILL_ID,
        name="自定义面试（JD 解析）",
        description="基于职位描述提取的面试方向",
        categories=categories,
        is_preset=False,
        source_jd=jd_text,
    )
