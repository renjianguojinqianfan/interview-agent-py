"""技能应用服务：编排 list/get/parse_jd，LLM 调用与域服务清洗纠正。"""

import logging

from app.application.skill.schemas import (
    CategoryDTO,
    DisplayDTO,
    JdParseResult,
    SkillCategoryDTO,
    SkillDTO,
)
from app.domain.entities.skill import JdCategory, Skill, SkillCategory
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.skill_service import (
    MIN_JD_LENGTH,
    build_category_ref_index,
    build_custom_skill,
    build_reference_file_list,
)
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.prompt_loader import load_prompt
from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer
from app.infrastructure.ai.structured_output import StructuredOutputInvoker
from app.infrastructure.skills.loader import SkillLoader

logger = logging.getLogger(__name__)


class SkillService:
    """技能管理应用服务：列表查询、详情查询、JD 解析。"""

    def __init__(
        self,
        loader: SkillLoader,
        llm_registry: LlmProviderRegistry,
        invoker: StructuredOutputInvoker,
        sanitizer: PromptSanitizer | None = None,
    ) -> None:
        self._loader = loader
        self._llm_registry = llm_registry
        self._invoker = invoker
        self._sanitizer = sanitizer or PromptSanitizer()

    async def list_skills(self) -> list[SkillDTO]:
        skills = await self._loader.load_skills()
        return [self._to_skill_dto(s) for s in skills]

    async def get_skill(self, skill_id: str) -> SkillDTO:
        skills = await self._loader.load_skills()
        for skill in skills:
            if skill.id == skill_id:
                return self._to_skill_dto(skill)
        raise BusinessException(ErrorCode.SKILL_NOT_FOUND, f"未找到面试主题: {skill_id}")

    async def parse_jd(self, jd_text: str) -> list[CategoryDTO]:
        if len(jd_text) < MIN_JD_LENGTH:
            raise BusinessException(
                ErrorCode.BAD_REQUEST,
                f"JD 内容太少（至少 {MIN_JD_LENGTH} 字），请补充后重试",
            )

        skills = await self._loader.load_skills()
        ref_list = build_reference_file_list(skills)
        ref_index = build_category_ref_index(skills)

        system_tpl = await load_prompt("jd-parse-system")
        system_prompt = system_tpl.format(referenceFileList=ref_list)
        sanitized = self._sanitizer.sanitize(jd_text) or ""
        user_prompt = self._sanitizer.wrap_with_delimiters("jd", sanitized)

        llm = await self._llm_registry.get_chat_client()
        result = await self._invoker.invoke(
            llm=llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=JdParseResult,
            error_code=ErrorCode.JD_PARSE_FAILED,
            error_prefix="JD 解析失败：",
            log_context="JD 解析",
        )

        if not result.categories:
            raise BusinessException(ErrorCode.JD_PARSE_FAILED, "JD 解析结果为空，请重试")

        jd_categories = [
            JdCategory(
                key=c.key,
                label=c.label,
                priority=c.priority,
                ref=c.ref,
                shared=c.shared,
            )
            for c in result.categories
        ]
        custom_skill = build_custom_skill(jd_categories, ref_index, jd_text)
        logger.info(
            "JD 解析完成: %d 个方向, %d 个匹配到参考文件",
            len(custom_skill.categories),
            sum(1 for c in custom_skill.categories if c.ref),
        )
        return [self._to_jd_category_dto(c) for c in custom_skill.categories]

    @staticmethod
    def _to_skill_dto(skill: Skill) -> SkillDTO:
        display: DisplayDTO | None = None
        if skill.icon or skill.gradient or skill.icon_bg or skill.icon_color:
            display = DisplayDTO(
                icon=skill.icon,
                gradient=skill.gradient,
                icon_bg=skill.icon_bg,
                icon_color=skill.icon_color,
            )
        return SkillDTO(
            id=skill.id,
            name=skill.name,
            description=skill.description,
            categories=[SkillService._to_skill_category_dto(c) for c in skill.categories],
            is_preset=skill.is_preset,
            source_jd=skill.source_jd,
            persona=skill.persona,
            display=display,
        )

    @staticmethod
    def _to_skill_category_dto(cat: SkillCategory) -> SkillCategoryDTO:
        return SkillCategoryDTO(
            key=cat.key,
            label=cat.label,
            priority=cat.priority,
            ref=cat.ref,
            shared=cat.shared,
        )

    @staticmethod
    def _to_jd_category_dto(cat: SkillCategory) -> CategoryDTO:
        return CategoryDTO(
            key=cat.key,
            label=cat.label,
            priority=cat.priority,
            ref=cat.ref,
            shared=cat.shared,
        )
