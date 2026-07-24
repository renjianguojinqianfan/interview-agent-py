"""技能管理 API DTO 与 LLM 输出模型。"""

from pydantic import BaseModel, Field

from app.api.responses import BaseSchema


class DisplayDTO(BaseSchema):
    icon: str | None = None
    gradient: str | None = None
    icon_bg: str | None = None
    icon_color: str | None = None


class SkillCategoryDTO(BaseSchema):
    key: str
    label: str
    priority: str
    ref: str | None = None
    shared: bool = False


class SkillDTO(BaseSchema):
    id: str
    name: str
    description: str | None = None
    categories: list[SkillCategoryDTO] = Field(default_factory=list)
    is_preset: bool = True
    source_jd: str | None = None
    persona: str | None = None
    display: DisplayDTO | None = None


class CategoryDTO(BaseSchema):
    key: str
    label: str
    priority: str
    ref: str | None = None
    shared: bool | None = None


class JdCategoryItem(BaseModel):
    """LLM JD 解析输出单项。"""

    key: str
    label: str
    priority: str
    ref: str | None = None
    shared: bool | None = None


class JdParseResult(BaseModel):
    """LLM JD 解析输出模型，字段对应 jd-parse-system.st 输出结构。"""

    categories: list[JdCategoryItem]


class ParseJdRequest(BaseSchema):
    jd_text: str
