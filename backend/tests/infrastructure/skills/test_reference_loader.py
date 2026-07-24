"""ReferenceLoader 单元测试：参考文件加载、缓存、段落构建。"""

from pathlib import Path

import pytest

from app.domain.entities.skill import Skill, SkillCategory
from app.infrastructure.skills.reference_loader import ReferenceLoader


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    shared = tmp_path / "_shared" / "references"
    shared.mkdir(parents=True)
    (shared / "java.md").write_text("Java 参考内容", encoding="utf-8")
    (shared / "mysql.md").write_text("MySQL 参考内容", encoding="utf-8")

    local = tmp_path / "java-backend" / "references"
    local.mkdir(parents=True)
    (local / "custom.md").write_text("Java 后端专属参考", encoding="utf-8")

    return tmp_path


@pytest.fixture()
def loader(skills_dir: Path) -> ReferenceLoader:
    return ReferenceLoader(skills_dir=skills_dir)


def _skill(categories: list[SkillCategory], skill_id: str = "java-backend") -> Skill:
    return Skill(
        id=skill_id,
        name="Java 后端",
        description=None,
        categories=categories,
    )


class TestLoad:
    async def test_load_shared_reference(self, loader: ReferenceLoader) -> None:
        content = await loader.load("java-backend", "java.md", shared=True)
        assert content == "Java 参考内容"

    async def test_load_skill_local_reference(self, loader: ReferenceLoader) -> None:
        content = await loader.load("java-backend", "custom.md", shared=False)
        assert content == "Java 后端专属参考"

    async def test_load_missing_returns_empty(self, loader: ReferenceLoader) -> None:
        content = await loader.load("java-backend", "missing.md", shared=True)
        assert content == ""

    async def test_cache_hits_on_second_load(self, loader: ReferenceLoader, skills_dir: Path) -> None:
        await loader.load("java-backend", "java.md", shared=True)
        # 删除源文件，第二次加载应走缓存
        (skills_dir / "_shared" / "references" / "java.md").unlink()
        content = await loader.load("java-backend", "java.md", shared=True)
        assert content == "Java 参考内容"


class TestBuildReferenceSection:
    async def test_builds_section_with_allocated_categories(self, loader: ReferenceLoader) -> None:
        skill = _skill(
            [
                SkillCategory(key="JAVA", label="Java", priority="CORE", ref="java.md", shared=True),
                SkillCategory(key="MYSQL", label="MySQL", priority="CORE", ref="mysql.md", shared=True),
                SkillCategory(key="PROJECT", label="项目", priority="ALWAYS_ONE"),
            ]
        )
        allocation = {"JAVA": 2, "MYSQL": 1, "PROJECT": 1}
        section = await loader.build_reference_section(skill, allocation)
        assert "Java 参考内容" in section
        assert "MySQL 参考内容" in section

    async def test_skips_zero_allocation_categories(self, loader: ReferenceLoader) -> None:
        skill = _skill(
            [
                SkillCategory(key="JAVA", label="Java", priority="CORE", ref="java.md", shared=True),
                SkillCategory(key="MYSQL", label="MySQL", priority="CORE", ref="mysql.md", shared=True),
            ]
        )
        allocation = {"JAVA": 2, "MYSQL": 0}
        section = await loader.build_reference_section(skill, allocation)
        assert "Java 参考内容" in section
        assert "MySQL 参考内容" not in section

    async def test_returns_empty_placeholder_when_no_refs(self, loader: ReferenceLoader) -> None:
        skill = _skill([SkillCategory(key="PROJECT", label="项目", priority="ALWAYS_ONE")])
        section = await loader.build_reference_section(skill, {"PROJECT": 1})
        assert "无参考题库" in section

    async def test_skips_categories_without_ref(self, loader: ReferenceLoader) -> None:
        skill = _skill(
            [
                SkillCategory(key="JAVA", label="Java", priority="CORE", ref="java.md", shared=True),
                SkillCategory(key="PROJECT", label="项目", priority="ALWAYS_ONE"),
            ]
        )
        allocation = {"JAVA": 1, "PROJECT": 1}
        section = await loader.build_reference_section(skill, allocation)
        assert "Java 参考内容" in section
