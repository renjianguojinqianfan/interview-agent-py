"""技能领域服务单元测试：纯函数算法，无框架依赖。"""

from app.domain.entities.skill import (
    JdCategory,
    RefMapping,
    Skill,
    SkillCategory,
)
from app.domain.services.skill_service import (
    build_category_ref_index,
    build_custom_skill,
    build_reference_file_list,
    calculate_allocation,
    sanitize_category_key,
    sanitize_category_label,
)


def _cat(
    key: str,
    label: str,
    priority: str,
    ref: str | None = None,
    shared: bool = False,
) -> SkillCategory:
    return SkillCategory(key=key, label=label, priority=priority, ref=ref, shared=shared)


class TestCalculateAllocation:
    def test_standard_mix(self) -> None:
        cats = [
            _cat("PROJECT", "项目", "ALWAYS_ONE"),
            _cat("JAVA", "Java", "CORE", "java.md", True),
            _cat("MYSQL", "MySQL", "CORE", "mysql.md", True),
            _cat("SPRING", "Spring", "NORMAL", "spring.md", True),
            _cat("REDIS", "Redis", "NORMAL", "redis.md", True),
        ]
        result = calculate_allocation(cats, 10)
        assert result["PROJECT"] == 1
        assert result["JAVA"] == 3
        assert result["MYSQL"] == 2
        assert result["SPRING"] == 2
        assert result["REDIS"] == 2
        assert sum(result.values()) == 10

    def test_total_zero(self) -> None:
        cats = [
            _cat("PROJECT", "项目", "ALWAYS_ONE"),
            _cat("JAVA", "Java", "CORE"),
            _cat("SPRING", "Spring", "NORMAL"),
        ]
        result = calculate_allocation(cats, 0)
        assert result.get("PROJECT") is None
        assert result["JAVA"] == 0
        assert result["SPRING"] == 0

    def test_total_less_than_category_count(self) -> None:
        cats = [
            _cat("PROJECT", "项目", "ALWAYS_ONE"),
            _cat("JAVA", "Java", "CORE"),
            _cat("SPRING", "Spring", "NORMAL"),
        ]
        result = calculate_allocation(cats, 2)
        assert result["PROJECT"] == 1
        assert result["JAVA"] == 1
        assert result["SPRING"] == 0
        assert sum(result.values()) == 2

    def test_only_core(self) -> None:
        cats = [_cat("JAVA", "Java", "CORE"), _cat("MYSQL", "MySQL", "CORE")]
        result = calculate_allocation(cats, 5)
        assert result["JAVA"] == 3
        assert result["MYSQL"] == 2
        assert sum(result.values()) == 5

    def test_empty_categories(self) -> None:
        result = calculate_allocation([], 5)
        assert result == {}

    def test_multiple_always_one(self) -> None:
        cats = [
            _cat("P1", "项目1", "ALWAYS_ONE"),
            _cat("P2", "项目2", "ALWAYS_ONE"),
            _cat("JAVA", "Java", "CORE"),
        ]
        result = calculate_allocation(cats, 3)
        assert result["P1"] == 1
        assert result["P2"] == 1
        assert result["JAVA"] == 1
        assert sum(result.values()) == 3

    def test_core_priority_over_normal_in_round_robin(self) -> None:
        cats = [
            _cat("JAVA", "Java", "CORE"),
            _cat("SPRING", "Spring", "NORMAL"),
        ]
        result = calculate_allocation(cats, 3)
        assert result["JAVA"] == 2
        assert result["SPRING"] == 1
        assert sum(result.values()) == 3


class TestSanitizeCategoryKey:
    def test_lowercase_to_upper(self) -> None:
        assert sanitize_category_key("java") == "JAVA"

    def test_illegal_chars_replaced(self) -> None:
        assert sanitize_category_key("java-script") == "JAVA_SCRIPT"

    def test_leading_digit_prefixed(self) -> None:
        assert sanitize_category_key("123abc") == "CAT_123ABC"

    def test_too_long_truncated(self) -> None:
        key = "A" * 60
        result = sanitize_category_key(key)
        assert len(result) == 50

    def test_empty_returns_unknown(self) -> None:
        assert sanitize_category_key("") == "UNKNOWN"
        assert sanitize_category_key("   ") == "UNKNOWN"
        assert sanitize_category_key(None) == "UNKNOWN"

    def test_already_valid(self) -> None:
        assert sanitize_category_key("JAVA_BACKEND") == "JAVA_BACKEND"


class TestSanitizeCategoryLabel:
    def test_newlines_stripped(self) -> None:
        assert sanitize_category_label("Java\r\n开发") == "Java 开发"

    def test_too_long_truncated(self) -> None:
        label = "x" * 60
        result = sanitize_category_label(label)
        assert len(result) == 50

    def test_empty_returns_default(self) -> None:
        assert sanitize_category_label("") == "未命名"
        assert sanitize_category_label(None) == "未命名"

    def test_normal_label(self) -> None:
        assert sanitize_category_label("MySQL") == "MySQL"


class TestBuildReferenceFileList:
    def test_dedup_by_filename(self) -> None:
        skills = [
            Skill(
                id="java-backend",
                name="java-backend",
                description=None,
                categories=[
                    _cat("JAVA", "Java", "CORE", "java.md", True),
                    _cat("MYSQL", "MySQL", "CORE", "mysql.md", True),
                ],
            ),
            Skill(
                id="python-backend",
                name="python-backend",
                description=None,
                categories=[
                    _cat("JAVA", "Java", "CORE", "java.md", True),
                    _cat("PYTHON", "Python", "CORE", "python.md", False),
                ],
            ),
        ]
        result = build_reference_file_list(skills)
        assert "| 文件名 | 范围 |" in result
        assert result.count("java.md") == 1
        assert "mysql.md" in result
        assert "python.md" in result
        assert "shared" in result
        assert "skill-local" in result

    def test_empty_skills(self) -> None:
        assert build_reference_file_list([]) == "（无可用参考文件）"

    def test_categories_without_ref_skipped(self) -> None:
        skills = [
            Skill(
                id="s1",
                name="s1",
                description=None,
                categories=[
                    _cat("PROJECT", "项目", "ALWAYS_ONE"),
                    _cat("JAVA", "Java", "CORE", "java.md", True),
                ],
            ),
        ]
        result = build_reference_file_list(skills)
        assert "java.md" in result
        assert "PROJECT" not in result


class TestBuildCategoryRefIndex:
    def test_first_skill_wins(self) -> None:
        skills = [
            Skill(
                id="s1",
                name="s1",
                description=None,
                categories=[_cat("JAVA", "Java", "CORE", "java.md", True)],
            ),
            Skill(
                id="s2",
                name="s2",
                description=None,
                categories=[_cat("JAVA", "Java", "CORE", "other.md", False)],
            ),
        ]
        index = build_category_ref_index(skills)
        assert index["JAVA"] == RefMapping(ref="java.md", shared=True, source_skill_id="s1")

    def test_skip_categories_without_ref(self) -> None:
        skills = [
            Skill(
                id="s1",
                name="s1",
                description=None,
                categories=[
                    _cat("PROJECT", "项目", "ALWAYS_ONE"),
                    _cat("JAVA", "Java", "CORE", "java.md", True),
                ],
            ),
        ]
        index = build_category_ref_index(skills)
        assert "PROJECT" not in index
        assert "JAVA" in index


class TestBuildCustomSkill:
    def test_corrected_via_index(self) -> None:
        index = {"JAVA": RefMapping(ref="java.md", shared=True, source_skill_id="java-backend")}
        jd_cats = [JdCategory(key="java", label="Java 开发", priority="CORE", ref="wrong.md", shared=False)]
        skill = build_custom_skill(jd_cats, index, "JD 文本")
        assert skill.id == "custom"
        assert skill.categories[0].key == "JAVA"
        assert skill.categories[0].label == "Java 开发"
        assert skill.categories[0].ref == "java.md"
        assert skill.categories[0].shared is True

    def test_unmatched_keeps_llm_values(self) -> None:
        index: dict[str, RefMapping] = {}
        jd_cats = [JdCategory(key="PYTHON", label="Python", priority="NORMAL", ref="py.md", shared=True)]
        skill = build_custom_skill(jd_cats, index, "JD 文本")
        assert skill.categories[0].ref == "py.md"
        assert skill.categories[0].shared is True

    def test_key_sanitized(self) -> None:
        index: dict[str, RefMapping] = {}
        jd_cats = [JdCategory(key="java-script", label="JS", priority="CORE")]
        skill = build_custom_skill(jd_cats, index, "")
        assert skill.categories[0].key == "JAVA_SCRIPT"

    def test_empty_jd_text_stored(self) -> None:
        skill = build_custom_skill([], {}, "")
        assert skill.source_jd == ""
        assert skill.categories == []

    def test_filters_invalid_categories(self) -> None:
        jd_cats = [
            JdCategory(key=None, label="NoKey", priority="CORE"),
            JdCategory(key="JAVA", label=None, priority="CORE"),
            JdCategory(key="JAVA", label="Java", priority="CORE"),
        ]
        skill = build_custom_skill(jd_cats, {}, "")
        assert len(skill.categories) == 1
