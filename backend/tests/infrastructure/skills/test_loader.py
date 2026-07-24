"""SkillLoader 单元测试：配置加载、front matter 解析、缓存。"""

from pathlib import Path

import pytest

from app.infrastructure.skills.loader import SkillLoader

_REAL_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "app" / "skills"


def _write_skill(base: Path, skill_id: str, meta: str, skill_md: str) -> None:
    d = base / skill_id
    d.mkdir(parents=True)
    (d / "skill.meta.yml").write_text(meta, encoding="utf-8")
    (d / "SKILL.md").write_text(skill_md, encoding="utf-8")


_SAMPLE_META = """\
displayName: 测试技能
display:
  icon: T
  gradient: from-gray-500 to-gray-700
  iconBg: bg-gray-100
  iconColor: text-gray-600
categories:
  - key: TEST_CORE
    label: 核心
    priority: CORE
    ref: test.md
    shared: true
  - key: PROJECT
    label: 项目
    priority: ALWAYS_ONE
"""

_SAMPLE_SKILL_MD = """\
---
name: test-skill
description: 测试用技能
---
# Overview
你是一位测试面试官。
"""


class TestSkillLoaderParse:
    @pytest.mark.asyncio
    async def test_parse_front_matter_and_persona(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "test-skill", _SAMPLE_META, _SAMPLE_SKILL_MD)
        loader = SkillLoader(skills_dir=tmp_path)
        skills = await loader.load_skills()
        assert len(skills) == 1
        skill = skills[0]
        assert skill.id == "test-skill"
        assert skill.name == "测试技能"
        assert skill.description == "测试用技能"
        assert skill.persona == "# Overview\n你是一位测试面试官。"
        assert skill.icon == "T"
        assert len(skill.categories) == 2
        assert skill.categories[0].key == "TEST_CORE"
        assert skill.categories[0].priority == "CORE"
        assert skill.categories[0].shared is True
        assert skill.categories[1].priority == "ALWAYS_ONE"

    @pytest.mark.asyncio
    async def test_display_name_fallback_to_front_matter_name(self, tmp_path: Path) -> None:
        meta = "categories:\n  - key: A\n    label: A\n    priority: CORE\n"
        _write_skill(tmp_path, "s1", meta, "---\nname: front-name\n---\nbody\n")
        loader = SkillLoader(skills_dir=tmp_path)
        skills = await loader.load_skills()
        assert skills[0].name == "front-name"

    @pytest.mark.asyncio
    async def test_skip_incomplete_skill_dir(self, tmp_path: Path) -> None:
        d = tmp_path / "incomplete"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
        _write_skill(tmp_path, "valid", _SAMPLE_META, _SAMPLE_SKILL_MD)
        loader = SkillLoader(skills_dir=tmp_path)
        skills = await loader.load_skills()
        assert len(skills) == 1
        assert skills[0].id == "valid"

    @pytest.mark.asyncio
    async def test_skip_shared_dirs(self, tmp_path: Path) -> None:
        _write_skill(tmp_path / "_shared", "x", _SAMPLE_META, _SAMPLE_SKILL_MD)
        _write_skill(tmp_path, "real", _SAMPLE_META, _SAMPLE_SKILL_MD)
        loader = SkillLoader(skills_dir=tmp_path)
        skills = await loader.load_skills()
        assert len(skills) == 1
        assert skills[0].id == "real"

    @pytest.mark.asyncio
    async def test_skip_invalid_front_matter(self, tmp_path: Path) -> None:
        (tmp_path / "bad").mkdir()
        (tmp_path / "bad" / "SKILL.md").write_text("no front matter here", encoding="utf-8")
        (tmp_path / "bad" / "skill.meta.yml").write_text(_SAMPLE_META, encoding="utf-8")
        _write_skill(tmp_path, "good", _SAMPLE_META, _SAMPLE_SKILL_MD)
        loader = SkillLoader(skills_dir=tmp_path)
        skills = await loader.load_skills()
        assert len(skills) == 1
        assert skills[0].id == "good"

    @pytest.mark.asyncio
    async def test_cache_returns_same_object(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "s1", _SAMPLE_META, _SAMPLE_SKILL_MD)
        loader = SkillLoader(skills_dir=tmp_path)
        first = await loader.load_skills()
        second = await loader.load_skills()
        assert first is second


class TestSkillLoaderReal:
    @pytest.mark.asyncio
    async def test_loads_ten_real_skills(self) -> None:
        loader = SkillLoader(skills_dir=_REAL_SKILLS_DIR)
        skills = await loader.load_skills()
        assert len(skills) == 10
        ids = {s.id for s in skills}
        assert "java-backend" in ids
        assert "ai-agent-dev" in ids
        for skill in skills:
            assert skill.name
            assert skill.categories
