"""技能配置加载器：从 app/skills/ 读取 SKILL.md + skill.meta.yml，返回 domain dataclass。"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from app.domain.entities.skill import Skill, SkillCategory

logger = logging.getLogger(__name__)

_FRONT_MATTER_PATTERN = re.compile(r"(?s)^---\s*\n(.*?)\n---\s*\n?(.*)$")
_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


class SkillLoader:
    """从 app/skills/ 加载预设技能配置，惰性缓存。"""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._skills_dir = skills_dir or _DEFAULT_SKILLS_DIR
        self._skills: list[Skill] | None = None

    async def load_skills(self) -> list[Skill]:
        if self._skills is not None:
            return self._skills
        self._skills = await asyncio.to_thread(self._load_sync)
        logger.info("加载 %d 个预设技能", len(self._skills))
        return self._skills

    def _load_sync(self) -> list[Skill]:
        skills: list[Skill] = []
        if not self._skills_dir.is_dir():
            logger.warning("技能目录不存在: %s", self._skills_dir)
            return skills
        for skill_dir in sorted(self._skills_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
                continue
            skill_file = skill_dir / "SKILL.md"
            meta_file = skill_dir / "skill.meta.yml"
            if not skill_file.exists() or not meta_file.exists():
                logger.warning("跳过不完整技能目录: %s", skill_dir.name)
                continue
            skill = self._parse_skill(skill_dir.name, skill_file, meta_file)
            if skill is not None:
                skills.append(skill)
        return skills

    def _parse_skill(self, skill_id: str, skill_file: Path, meta_file: Path) -> Skill | None:
        markdown = skill_file.read_text(encoding="utf-8")
        matcher = _FRONT_MATTER_PATTERN.match(markdown)
        if not matcher:
            logger.warning("SKILL.md 格式错误（缺少 front matter）: %s", skill_id)
            return None

        front_matter = yaml.safe_load(matcher.group(1)) or {}
        body = matcher.group(2).strip() if matcher.group(2) else ""
        meta = yaml.safe_load(meta_file.read_text(encoding="utf-8")) or {}

        name = meta.get("displayName") or front_matter.get("name") or skill_id
        if not name:
            logger.warning("跳过无效 Skill（缺少 name）: %s", skill_id)
            return None

        display = meta.get("display") or {}
        return Skill(
            id=skill_id,
            name=name,
            description=front_matter.get("description"),
            categories=self._parse_categories(meta.get("categories", [])),
            is_preset=True,
            persona=body or None,
            icon=display.get("icon"),
            gradient=display.get("gradient"),
            icon_bg=display.get("iconBg"),
            icon_color=display.get("iconColor"),
        )

    @staticmethod
    def _parse_categories(raw: list[Any]) -> list[SkillCategory]:
        categories: list[SkillCategory] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            categories.append(
                SkillCategory(
                    key=item.get("key", ""),
                    label=item.get("label", ""),
                    priority=item.get("priority", ""),
                    ref=item.get("ref"),
                    shared=bool(item.get("shared", False)),
                )
            )
        return categories
