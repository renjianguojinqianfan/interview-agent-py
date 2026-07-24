"""出题领域服务单元测试：纯函数算法，无框架依赖。"""

from app.domain.entities.interview import (
    MAX_HISTORICAL_QUESTIONS,
    HistoricalQuestion,
    InterviewQuestion,
    get_default_fallback_questions,
)
from app.domain.entities.skill import Skill, SkillCategory
from app.domain.services.question_gen import (
    attach_follow_ups,
    build_allocation_table,
    build_difficulty_description,
    build_historical_section,
    dedupe_historical,
    generate_fallback_questions,
    split_resume_direction_counts,
)


def _question(index: int, q: str = "题", type_: str = "JAVA", cat: str = "Java") -> InterviewQuestion:
    return InterviewQuestion(question_index=index, question=q, type=type_, category=cat)


def _skill(persona: str | None = "Java 后端专家") -> Skill:
    return Skill(
        id="java-backend",
        name="Java 后端",
        description="Java 后端面试",
        categories=[SkillCategory(key="JAVA", label="Java", priority="CORE")],
        persona=persona,
    )


class TestSplitResumeDirectionCounts:
    def test_standard_60_40(self) -> None:
        resume_count, direction_count = split_resume_direction_counts(10)
        assert resume_count == 6
        assert direction_count == 4

    def test_remainder_goes_to_resume(self) -> None:
        # total=5 -> 60%*5=3, 40%*5=2
        resume_count, direction_count = split_resume_direction_counts(5)
        assert resume_count == 3
        assert direction_count == 2

    def test_total_one(self) -> None:
        resume_count, direction_count = split_resume_direction_counts(1)
        assert resume_count == 1
        assert direction_count == 0

    def test_total_zero(self) -> None:
        resume_count, direction_count = split_resume_direction_counts(0)
        assert resume_count == 0
        assert direction_count == 0

    def test_custom_ratio(self) -> None:
        resume_count, direction_count = split_resume_direction_counts(10, ratio=0.5)
        assert resume_count == 5
        assert direction_count == 5


class TestBuildAllocationTable:
    def test_standard(self) -> None:
        categories = [
            SkillCategory(key="JAVA", label="Java", priority="CORE"),
            SkillCategory(key="MYSQL", label="MySQL", priority="CORE"),
        ]
        allocation = {"JAVA": 2, "MYSQL": 1}
        table = build_allocation_table(allocation, categories)
        assert "Java" in table
        assert "MySQL" in table
        assert "2" in table
        assert "1" in table

    def test_empty_allocation(self) -> None:
        categories = [SkillCategory(key="JAVA", label="Java", priority="CORE")]
        table = build_allocation_table({}, categories)
        assert "无" in table or "0" in table


class TestBuildHistoricalSection:
    def test_standard(self) -> None:
        historical = [
            HistoricalQuestion(question="Redis 持久化", type="REDIS", topic_summary="Redis 持久化"),
            HistoricalQuestion(question="MySQL 索引", type="MYSQL", topic_summary="MySQL 索引"),
        ]
        section = build_historical_section(historical)
        assert "Redis 持久化" in section
        assert "MySQL 索引" in section

    def test_empty(self) -> None:
        section = build_historical_section([])
        assert "无" in section or section.strip() != ""


class TestBuildDifficultyDescription:
    def test_junior(self) -> None:
        desc = build_difficulty_description("junior")
        assert "初级" in desc or "junior" in desc.lower()

    def test_mid(self) -> None:
        desc = build_difficulty_description("mid")
        assert "中级" in desc or "mid" in desc.lower()

    def test_senior(self) -> None:
        desc = build_difficulty_description("senior")
        assert "高级" in desc or "senior" in desc.lower()

    def test_unknown(self) -> None:
        desc = build_difficulty_description("unknown")
        assert "中级" in desc or "mid" in desc.lower()


class TestDedupeHistorical:
    def test_dedupe_by_topic_summary(self) -> None:
        raw = [
            HistoricalQuestion(question="Q1", type="JAVA", topic_summary="Java 集合"),
            HistoricalQuestion(question="Q2", type="JAVA", topic_summary="Java 集合"),  # 重复
            HistoricalQuestion(question="Q3", type="MYSQL", topic_summary="MySQL 索引"),
        ]
        result = dedupe_historical(raw)
        assert len(result) == 2

    def test_normalize_topic_summary(self) -> None:
        raw = [
            HistoricalQuestion(question="Q1", type="JAVA", topic_summary="  java 集合  "),
            HistoricalQuestion(question="Q2", type="JAVA", topic_summary="JAVA 集合"),
        ]
        result = dedupe_historical(raw)
        assert len(result) == 1

    def test_limit_max(self) -> None:
        raw = [
            HistoricalQuestion(question=f"Q{i}", type="JAVA", topic_summary=f"topic{i}")
            for i in range(MAX_HISTORICAL_QUESTIONS + 10)
        ]
        result = dedupe_historical(raw)
        assert len(result) == MAX_HISTORICAL_QUESTIONS

    def test_empty(self) -> None:
        assert dedupe_historical([]) == []


class TestGenerateFallbackQuestions:
    def test_with_persona(self) -> None:
        skill = _skill(persona="Java 后端专家")
        questions = generate_fallback_questions(skill, 3)
        assert len(questions) == 3
        assert all(q.question for q in questions)
        assert all(not q.is_follow_up for q in questions)

    def test_without_persona(self) -> None:
        skill = _skill(persona=None)
        questions = generate_fallback_questions(skill, 3)
        assert len(questions) == 3
        # 应使用硬编码兜底题
        fallbacks = get_default_fallback_questions()
        assert questions[0].question in fallbacks

    def test_count_exceeds_fallback_pool(self) -> None:
        skill = _skill(persona=None)
        questions = generate_fallback_questions(skill, 10)
        assert len(questions) == 10
        # 应循环复用
        fallbacks = get_default_fallback_questions()
        assert questions[0].question == fallbacks[0]
        assert questions[5].question == fallbacks[0]  # 循环复用

    def test_count_zero(self) -> None:
        skill = _skill()
        assert generate_fallback_questions(skill, 0) == []

    def test_question_index_sequential(self) -> None:
        skill = _skill()
        questions = generate_fallback_questions(skill, 3)
        assert [q.question_index for q in questions] == [0, 1, 2]


class TestAttachFollowUps:
    def test_standard_attach(self) -> None:
        main_qs = [_question(i, f"主问题{i}") for i in range(3)]
        follow_up_map = {
            0: ["追问0a", "追问0b"],
            1: ["追问1a"],
            2: [],
        }
        result = attach_follow_ups(main_qs, follow_up_map, max_follow_up=2)
        # 3 主问题 + 2+1+0 追问 = 6
        assert len(result) == 6
        # questionIndex 重排连续
        assert [q.question_index for q in result] == list(range(6))
        # 主问题 is_follow_up=False
        assert result[0].is_follow_up is False
        # 追问 is_follow_up=True
        follow_ups = [q for q in result if q.is_follow_up]
        assert len(follow_ups) == 3
        # 第一个追问的 parent 指向主问题 0
        assert follow_ups[0].parent_question_index == 0

    def test_max_follow_up_limit(self) -> None:
        main_qs = [_question(0, "主问题")]
        follow_up_map = {0: ["q1", "q2", "q3", "q4"]}  # 4 个追问
        result = attach_follow_ups(main_qs, follow_up_map, max_follow_up=2)
        # 1 主问题 + 2 追问（截断）= 3
        assert len(result) == 3
        follow_ups = [q for q in result if q.is_follow_up]
        assert len(follow_ups) == 2

    def test_empty_follow_ups(self) -> None:
        main_qs = [_question(0, "主问题")]
        result = attach_follow_ups(main_qs, {}, max_follow_up=2)
        assert len(result) == 1
        assert result[0].is_follow_up is False

    def test_no_main_questions(self) -> None:
        result = attach_follow_ups([], {0: ["q1"]}, max_follow_up=2)
        assert result == []
