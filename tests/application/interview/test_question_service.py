from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.interview.question_service import QuestionService
from app.application.interview.schemas import QuestionItem, QuestionList
from app.domain.entities.skill import Skill, SkillCategory


def _skill() -> Skill:
    return Skill(
        id="java-backend",
        name="Java 后端",
        description="Java 后端面试",
        categories=[
            SkillCategory(key="JAVA", label="Java", priority="CORE", ref="java.md", shared=True),
            SkillCategory(key="PROJECT", label="项目", priority="ALWAYS_ONE"),
        ],
        persona="Java 后端专家",
    )


def _question_list(n: int, prefix: str = "题") -> QuestionList:
    return QuestionList(
        questions=[
            QuestionItem(
                question=f"{prefix}{i}",
                type="JAVA",
                category="Java",
                topicSummary=f"topic{i}",
                followUps=[],
            )
            for i in range(n)
        ]
    )


@pytest.fixture()
def mock_invoker() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_llm_registry() -> MagicMock:
    registry = MagicMock()
    registry.get_chat_client = AsyncMock(return_value=MagicMock())
    return registry


@pytest.fixture()
def mock_skill_loader() -> MagicMock:
    loader = MagicMock()
    loader.load_skills = AsyncMock(return_value=[_skill()])
    return loader


@pytest.fixture()
def mock_reference_loader() -> MagicMock:
    loader = MagicMock()
    loader.build_reference_section = AsyncMock(return_value="参考内容")
    return loader


@pytest.fixture()
def service(
    mock_skill_loader: MagicMock,
    mock_reference_loader: MagicMock,
    mock_llm_registry: MagicMock,
    mock_invoker: MagicMock,
) -> QuestionService:
    return QuestionService(
        skill_loader=mock_skill_loader,
        reference_loader=mock_reference_loader,
        llm_registry=mock_llm_registry,
        invoker=mock_invoker,
    )


def _mock_prompt() -> MagicMock:
    tpl = MagicMock()
    tpl.format.return_value = "prompt content"
    return tpl


@pytest.fixture()
def mock_load_prompt() -> Iterator[MagicMock]:
    with patch("app.application.interview.question_service.load_prompt") as mock:
        mock.return_value = _mock_prompt()
        yield mock


class TestGenerateDirectionOnly:
    async def test_direction_success(
        self,
        service: QuestionService,
        mock_invoker: MagicMock,
        mock_load_prompt: MagicMock,
    ) -> None:
        mock_invoker.invoke = AsyncMock(return_value=_question_list(5))

        result = await service.generate(
            skill_id="java-backend",
            difficulty="mid",
            resume_text=None,
            question_count=5,
            historical=[],
        )

        assert len(result) == 5
        assert result[0].question == "题0"

    async def test_direction_failure_falls_back(
        self,
        service: QuestionService,
        mock_invoker: MagicMock,
        mock_load_prompt: MagicMock,
    ) -> None:
        mock_invoker.invoke = AsyncMock(side_effect=Exception("LLM down"))

        result = await service.generate(
            skill_id="java-backend",
            difficulty="mid",
            resume_text=None,
            question_count=3,
            historical=[],
        )

        assert len(result) == 3
        assert all(q.question for q in result)


class TestGenerateWithResume:
    async def test_both_success_merges_60_40(
        self,
        service: QuestionService,
        mock_invoker: MagicMock,
        mock_load_prompt: MagicMock,
    ) -> None:
        resume_result = _question_list(6, "简历题")
        direction_result = _question_list(4, "方向题")
        mock_invoker.invoke = AsyncMock(side_effect=[resume_result, direction_result])

        result = await service.generate(
            skill_id="java-backend",
            difficulty="mid",
            resume_text="简历内容",
            question_count=10,
            historical=[],
        )

        assert len(result) == 10
        questions_text = [q.question for q in result]
        assert "简历题0" in questions_text
        assert "方向题0" in questions_text

    async def test_resume_only_falls_back_to_resume(
        self,
        service: QuestionService,
        mock_invoker: MagicMock,
        mock_load_prompt: MagicMock,
    ) -> None:
        resume_result = _question_list(4, "简历题")
        mock_invoker.invoke = AsyncMock(side_effect=[resume_result, Exception("方向出题失败")])

        result = await service.generate(
            skill_id="java-backend",
            difficulty="mid",
            resume_text="简历内容",
            question_count=6,
            historical=[],
        )

        # split(6)=(4,2)，简历题 4 个，方向失败，降级用简历题 4 个
        assert len(result) == 4
        assert all("简历题" in q.question for q in result)

    async def test_direction_only_falls_back_to_direction(
        self,
        service: QuestionService,
        mock_invoker: MagicMock,
        mock_load_prompt: MagicMock,
    ) -> None:
        direction_result = _question_list(2, "方向题")
        mock_invoker.invoke = AsyncMock(side_effect=[Exception("简历出题失败"), direction_result])

        result = await service.generate(
            skill_id="java-backend",
            difficulty="mid",
            resume_text="简历内容",
            question_count=4,
            historical=[],
        )

        # split(4)=(2,2)，方向题 2 个，简历失败，降级用方向题 2 个
        assert len(result) == 2
        assert all("方向题" in q.question for q in result)

    async def test_both_failure_falls_back_to_fallback(
        self,
        service: QuestionService,
        mock_invoker: MagicMock,
        mock_load_prompt: MagicMock,
    ) -> None:
        mock_invoker.invoke = AsyncMock(side_effect=[Exception("简历失败"), Exception("方向失败")])

        result = await service.generate(
            skill_id="java-backend",
            difficulty="mid",
            resume_text="简历内容",
            question_count=3,
            historical=[],
        )

        assert len(result) == 3
        assert all(q.question for q in result)


class TestGenerateWithCustomSkill:
    async def test_custom_skill_from_jd(
        self,
        service: QuestionService,
        mock_invoker: MagicMock,
        mock_load_prompt: MagicMock,
    ) -> None:
        mock_invoker.invoke = AsyncMock(return_value=_question_list(3))

        custom_categories = [
            {"key": "SPRING", "label": "Spring", "priority": "CORE", "ref": "spring.md", "shared": True}
        ]
        result = await service.generate(
            skill_id="custom",
            difficulty="mid",
            resume_text=None,
            question_count=3,
            historical=[],
            custom_categories=custom_categories,
            jd_text="Java 后端 JD",
        )

        assert len(result) == 3

    async def test_custom_skill_sanitizes_unsanitized_keys(
        self,
        service: QuestionService,
    ) -> None:
        """P2: custom_categories 未经 JD 解析 API，需通过 build_custom_skill 清洗 key。"""
        custom_categories = [
            {"key": "spring boot", "label": "Spring Boot", "priority": "CORE", "ref": None, "shared": False}
        ]
        skill = await service._build_custom_skill_from_dict(custom_categories, "JD text")
        assert skill.categories[0].key == "SPRING_BOOT"
        assert skill.categories[0].label == "Spring Boot"


class TestFollowUpAttachment:
    async def test_follow_ups_attached(
        self,
        service: QuestionService,
        mock_invoker: MagicMock,
        mock_load_prompt: MagicMock,
    ) -> None:
        result_with_followups = QuestionList(
            questions=[
                QuestionItem(
                    question="主问题",
                    type="JAVA",
                    category="Java",
                    topicSummary="topic",
                    followUps=["追问1", "追问2"],
                )
            ]
        )
        mock_invoker.invoke = AsyncMock(return_value=result_with_followups)

        result = await service.generate(
            skill_id="java-backend",
            difficulty="mid",
            resume_text=None,
            question_count=1,
            historical=[],
        )

        assert len(result) == 3
        assert result[0].is_follow_up is False
        assert result[1].is_follow_up is True
        assert result[1].parent_question_index == 0
        assert result[2].is_follow_up is True
        assert result[2].parent_question_index == 0


class TestGenerateProviderResolution:
    """#29 llmProvider 按名解析：字符串供应商名 → int id → get_chat_client。"""

    async def test_generate_resolves_llm_provider_by_name(
        self,
        service: QuestionService,
        mock_invoker: MagicMock,
        mock_llm_registry: MagicMock,
        mock_load_prompt: MagicMock,
    ) -> None:
        mock_invoker.invoke = AsyncMock(return_value=_question_list(3))
        mock_llm_registry.resolve_provider_id_by_name = AsyncMock(return_value=7)

        await service.generate(
            skill_id="java-backend",
            difficulty="mid",
            resume_text="我的简历",
            question_count=3,
            historical=[],
            llm_provider="dashscope",
        )

        mock_llm_registry.resolve_provider_id_by_name.assert_awaited_with("dashscope")
        # 解析出的 int id 传给 get_chat_client
        assert any(c.args and c.args[0] == 7 for c in mock_llm_registry.get_chat_client.await_args_list)

    async def test_generate_default_provider_skips_resolution(
        self,
        service: QuestionService,
        mock_invoker: MagicMock,
        mock_llm_registry: MagicMock,
        mock_load_prompt: MagicMock,
    ) -> None:
        """未传 llmProvider 时不触发名称解析（回退默认 provider）。"""
        mock_invoker.invoke = AsyncMock(return_value=_question_list(3))
        mock_llm_registry.resolve_provider_id_by_name = AsyncMock()

        await service.generate(
            skill_id="java-backend",
            difficulty="mid",
            resume_text=None,
            question_count=3,
            historical=[],
        )

        mock_llm_registry.resolve_provider_id_by_name.assert_not_awaited()
