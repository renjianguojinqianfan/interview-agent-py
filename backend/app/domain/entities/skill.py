"""技能领域实体：纯 dataclass + enum，零框架依赖。"""

from dataclasses import dataclass
from enum import StrEnum


class CategoryPriority(StrEnum):
    CORE = "CORE"
    NORMAL = "NORMAL"
    ALWAYS_ONE = "ALWAYS_ONE"


@dataclass(frozen=True)
class SkillCategory:
    key: str
    label: str
    priority: str
    ref: str | None = None
    shared: bool = False


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str | None
    categories: list[SkillCategory]
    is_preset: bool = True
    persona: str | None = None
    source_jd: str | None = None
    icon: str | None = None
    gradient: str | None = None
    icon_bg: str | None = None
    icon_color: str | None = None


@dataclass(frozen=True)
class JdCategory:
    key: str | None
    label: str | None
    priority: str
    ref: str | None = None
    shared: bool | None = None


@dataclass(frozen=True)
class RefMapping:
    ref: str
    shared: bool
    source_skill_id: str
