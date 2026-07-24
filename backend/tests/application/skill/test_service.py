"""SkillService 单元测试：list/get/parse_jd 编排。"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.skill.schemas import JdCategoryItem, JdParseResult
from app.application.skill.service import SkillService
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.skills.loader import SkillLoader

_REAL_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "app" / "skills"
_JD_TEXT = "我们需要一位 Java 后端工程师，熟悉 Spring Boot、MySQL、Redis，负责高并发系统设计。"


@pytest.fixture
def service() -> SkillService:
    loader = SkillLoader(skills_dir=_REAL_SKILLS_DIR)
    llm_registry = MagicMock()
    llm_registry.get_chat_client = AsyncMock(return_value=MagicMock())
    invoker = MagicMock()
    invoker.invoke = AsyncMock()
    return SkillService(loader=loader, llm_registry=llm_registry, invoker=invoker)


class TestListSkills:
    @pytest.mark.asyncio
    async def test_returns_ten_skills(self, service: SkillService) -> None:
        skills = await service.list_skills()
        assert len(skills) == 10
        assert all(s.is_preset for s in skills)

    @pytest.mark.asyncio
    async def test_skill_has_display_and_categories(self, service: SkillService) -> None:
        skills = await service.list_skills()
        java = next(s for s in skills if s.id == "java-backend")
        assert java.name
        assert java.categories
        assert java.display is not None
        assert java.display.icon


class TestGetSkill:
    @pytest.mark.asyncio
    async def test_found(self, service: SkillService) -> None:
        skill = await service.get_skill("java-backend")
        assert skill.id == "java-backend"
        assert skill.name

    @pytest.mark.asyncio
    async def test_not_found_raises(self, service: SkillService) -> None:
        with pytest.raises(BusinessException) as exc:
            await service.get_skill("nonexistent")
        assert exc.value.error_code == ErrorCode.SKILL_NOT_FOUND


class TestParseJd:
    @pytest.mark.asyncio
    async def test_too_short_raises(self, service: SkillService) -> None:
        with pytest.raises(BusinessException) as exc:
            await service.parse_jd("短文本")
        assert exc.value.error_code == ErrorCode.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_parses_and_corrects(self, service: SkillService) -> None:
        invoker = service._invoker
        invoker.invoke.return_value = JdParseResult(
            categories=[
                JdCategoryItem(
                    key="java",
                    label="Java",
                    priority="CORE",
                    ref="wrong.md",
                    shared=False,
                ),
                JdCategoryItem(
                    key="obscure_tech",
                    label="Obscure",
                    priority="NORMAL",
                    ref="obs.md",
                    shared=True,
                ),
            ]
        )
        result = await service.parse_jd(_JD_TEXT)
        assert len(result) == 2
        java_cat = next(c for c in result if c.key == "JAVA")
        assert java_cat.ref == "java.md"
        assert java_cat.shared is True
        obscure_cat = next(c for c in result if c.key == "OBSCURE_TECH")
        assert obscure_cat.ref == "obs.md"
        assert obscure_cat.shared is True

    @pytest.mark.asyncio
    async def test_empty_result_raises(self, service: SkillService) -> None:
        service._invoker.invoke.return_value = JdParseResult(categories=[])
        with pytest.raises(BusinessException) as exc:
            await service.parse_jd(_JD_TEXT)
        assert exc.value.error_code == ErrorCode.JD_PARSE_FAILED
