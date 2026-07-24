"""参考题库加载器：从 app/skills/ 加载 reference .md 内容，构建 prompt 用的参考段落。

路径约定（与 Java 端一致）：
- shared=true:  skills/_shared/references/{ref}
- shared=false: skills/{skillId}/references/{ref}
"""

import asyncio
import logging
from pathlib import Path

from app.domain.entities.skill import Skill

logger = logging.getLogger(__name__)

_DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"
_EMPTY_REFERENCE_PLACEHOLDER = "（无参考题库）"


class ReferenceLoader:
    """参考题库文件加载器，进程内缓存。"""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._skills_dir = skills_dir or _DEFAULT_SKILLS_DIR
        self._cache: dict[tuple[str, str, bool], str] = {}

    async def load(self, skill_id: str, ref: str, shared: bool) -> str:
        cache_key = (skill_id, ref, shared)
        if cache_key in self._cache:
            return self._cache[cache_key]
        content = await asyncio.to_thread(self._load_sync, skill_id, ref, shared)
        self._cache[cache_key] = content
        return content

    async def build_reference_section(
        self,
        skill: Skill,
        allocation: dict[str, int],
    ) -> str:
        """构建 prompt 用的参考题库段落，按 allocation 过滤（0 题量的 category 跳过）。"""
        sections: list[str] = []
        for cat in skill.categories:
            if not cat.ref:
                continue
            if allocation.get(cat.key, 0) == 0:
                continue
            content = await self.load(skill.id, cat.ref, cat.shared)
            if content:
                sections.append(f"## {cat.label}\n\n{content}")
        if not sections:
            return _EMPTY_REFERENCE_PLACEHOLDER
        return "\n\n".join(sections)

    def _load_sync(self, skill_id: str, ref: str, shared: bool) -> str:
        if shared:
            path = self._skills_dir / "_shared" / "references" / ref
        else:
            path = self._skills_dir / skill_id / "references" / ref
        if not path.is_file():
            logger.warning("参考文件不存在: %s", path)
            return ""
        return path.read_text(encoding="utf-8")
