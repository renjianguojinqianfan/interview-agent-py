"""出题应用服务：LLM 编排（并行 gather + 降级链），依赖 domain 服务纯函数。"""

import asyncio
import logging

from app.application.interview.schemas import QuestionList
from app.domain.entities.interview import (
    DEFAULT_FOLLOW_UP_COUNT,
    HistoricalQuestion,
    InterviewQuestion,
)
from app.domain.entities.skill import JdCategory, Skill
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.question_gen import (
    attach_follow_ups,
    build_allocation_table,
    build_difficulty_description,
    build_historical_section,
    generate_fallback_questions,
    split_resume_direction_counts,
)
from app.domain.services.skill_service import build_category_ref_index, build_custom_skill, calculate_allocation
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.prompt_loader import load_prompt
from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer
from app.infrastructure.ai.structured_output import StructuredOutputInvoker
from app.infrastructure.skills.loader import SkillLoader
from app.infrastructure.skills.reference_loader import ReferenceLoader

logger = logging.getLogger(__name__)

type MainQuestionWithFollowUps = tuple[InterviewQuestion, list[str]]
"""LLM 调用返回值：(主问题, 追问文本列表)。合并/截断后由 attach_follow_ups 统一拼接。"""


class QuestionService:
    """出题 LLM 编排服务：有简历并行出题 + 降级链，无简历方向出题。"""

    def __init__(
        self,
        skill_loader: SkillLoader,
        reference_loader: ReferenceLoader,
        llm_registry: LlmProviderRegistry,
        invoker: StructuredOutputInvoker,
        sanitizer: PromptSanitizer | None = None,
    ) -> None:
        self._skill_loader = skill_loader
        self._reference_loader = reference_loader
        self._llm_registry = llm_registry
        self._invoker = invoker
        self._sanitizer = sanitizer or PromptSanitizer()

    async def generate(
        self,
        skill_id: str,
        difficulty: str,
        resume_text: str | None,
        question_count: int,
        historical: list[HistoricalQuestion],
        custom_categories: list[dict[str, object]] | None = None,
        jd_text: str | None = None,
        llm_provider: str | None = None,
    ) -> list[InterviewQuestion]:
        skill = await self._resolve_skill(skill_id, custom_categories, jd_text)
        provider_id = None
        if llm_provider:
            # 按名解析供应商（早早抛 PROVIDER_NOT_FOUND，早于并行 gather 的兵底链，保证非静默回退）
            provider_id = await self._llm_registry.resolve_provider_id_by_name(llm_provider)
        if resume_text:
            return await self._generate_with_resume(
                skill, difficulty, resume_text, question_count, historical, jd_text, provider_id
            )
        return await self._generate_direction_only(skill, difficulty, question_count, historical, jd_text, provider_id)

    async def _generate_with_resume(
        self,
        skill: Skill,
        difficulty: str,
        resume_text: str,
        question_count: int,
        historical: list[HistoricalQuestion],
        jd_text: str | None,
        llm_provider_id: int | None,
    ) -> list[InterviewQuestion]:
        resume_count, direction_count = split_resume_direction_counts(question_count)
        resume_task = self._call_resume_llm(skill, difficulty, resume_text, resume_count, historical, llm_provider_id)
        direction_task = self._call_direction_llm(
            skill, difficulty, direction_count, historical, jd_text, llm_provider_id
        )
        results = await asyncio.gather(resume_task, direction_task, return_exceptions=True)

        resume_qs = results[0] if isinstance(results[0], list) else None
        direction_qs = results[1] if isinstance(results[1], list) else None

        if resume_qs is not None and direction_qs is not None:
            logger.info("并行出题成功: 简历题=%d, 方向题=%d", len(resume_qs), len(direction_qs))
            return self._merge_with_follow_ups(resume_qs, direction_qs, question_count)
        if resume_qs is not None:
            logger.warning("方向出题失败，使用简历题兜底: count=%d", len(resume_qs))
            return self._cap_and_attach(resume_qs, question_count)
        if direction_qs is not None:
            logger.warning("简历出题失败，使用方向题兜底: count=%d", len(direction_qs))
            return self._cap_and_attach(direction_qs, question_count)

        logger.warning("简历题与方向题均失败，使用兜底题")
        return generate_fallback_questions(skill, question_count)

    async def _generate_direction_only(
        self,
        skill: Skill,
        difficulty: str,
        question_count: int,
        historical: list[HistoricalQuestion],
        jd_text: str | None,
        llm_provider_id: int | None,
    ) -> list[InterviewQuestion]:
        try:
            qs = await self._call_direction_llm(skill, difficulty, question_count, historical, jd_text, llm_provider_id)
            return self._cap_and_attach(qs, question_count)
        except Exception as e:
            logger.warning("方向出题失败，使用兜底题: %s", e)
            return generate_fallback_questions(skill, question_count)

    async def _call_resume_llm(
        self,
        skill: Skill,
        difficulty: str,
        resume_text: str,
        question_count: int,
        historical: list[HistoricalQuestion],
        llm_provider_id: int | None,
    ) -> list[MainQuestionWithFollowUps]:
        if question_count <= 0:
            return []
        system_tpl = await load_prompt("interview-question-resume-system")
        user_tpl = await load_prompt("interview-question-resume-user")
        system_prompt = system_tpl.format()
        sanitized_resume = self._sanitizer.sanitize(resume_text) or ""
        wrapped_resume = self._sanitizer.wrap_with_delimiters("简历内容", sanitized_resume)
        user_prompt = user_tpl.format(
            questionCount=question_count,
            followUpCount=DEFAULT_FOLLOW_UP_COUNT,
            skillName=skill.name,
            skillDescription=skill.description or "",
            difficultyDescription=build_difficulty_description(difficulty),
            resumeText=wrapped_resume,
            historicalSection=build_historical_section(historical),
        )
        llm = await self._llm_registry.get_chat_client(llm_provider_id)
        result = await self._invoker.invoke(
            llm=llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=QuestionList,
            error_code=ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED,
            error_prefix="简历出题失败：",
            log_context="简历出题",
        )
        return self._convert_to_questions(result, question_count)

    async def _call_direction_llm(
        self,
        skill: Skill,
        difficulty: str,
        question_count: int,
        historical: list[HistoricalQuestion],
        jd_text: str | None,
        llm_provider_id: int | None,
    ) -> list[MainQuestionWithFollowUps]:
        if question_count <= 0:
            return []
        allocation = calculate_allocation(skill.categories, question_count)
        reference_section = await self._reference_loader.build_reference_section(skill, allocation)
        system_tpl = await load_prompt("interview-question-skill-system")
        user_tpl = await load_prompt("interview-question-skill-user")
        system_prompt = system_tpl.format()
        jd_section = self._build_jd_section(jd_text)
        user_prompt = user_tpl.format(
            questionCount=question_count,
            followUpCount=DEFAULT_FOLLOW_UP_COUNT,
            difficultyDescription=build_difficulty_description(difficulty),
            skillName=skill.name,
            skillDescription=skill.description or "",
            allocationTable=build_allocation_table(allocation, skill.categories),
            historicalSection=build_historical_section(historical),
            referenceSection=reference_section,
            jdSection=jd_section,
        )
        llm = await self._llm_registry.get_chat_client(llm_provider_id)
        result = await self._invoker.invoke(
            llm=llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=QuestionList,
            error_code=ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED,
            error_prefix="方向出题失败：",
            log_context="方向出题",
        )
        return self._convert_to_questions(result, question_count)

    async def _resolve_skill(
        self,
        skill_id: str,
        custom_categories: list[dict[str, object]] | None,
        jd_text: str | None,
    ) -> Skill:
        if custom_categories and jd_text:
            return await self._build_custom_skill_from_dict(custom_categories, jd_text)
        skills = await self._skill_loader.load_skills()
        for s in skills:
            if s.id == skill_id:
                return s
        raise BusinessException(ErrorCode.SKILL_NOT_FOUND, f"未找到面试主题: {skill_id}")

    async def _build_custom_skill_from_dict(
        self,
        custom_categories: list[dict[str, object]],
        jd_text: str,
    ) -> Skill:
        """通过 domain build_custom_skill 构建，复用 sanitize_category_key/label + ref 纠正。"""
        skills = await self._skill_loader.load_skills()
        ref_index = build_category_ref_index(skills)
        jd_categories: list[JdCategory] = []
        for item in custom_categories:
            ref_val = item.get("ref")
            shared_val = item.get("shared")
            jd_categories.append(
                JdCategory(
                    key=str(item.get("key", "")),
                    label=str(item.get("label", "")),
                    priority=str(item.get("priority", "NORMAL")),
                    ref=ref_val if isinstance(ref_val, str) else None,
                    shared=bool(shared_val) if shared_val is not None else None,
                )
            )
        return build_custom_skill(jd_categories, ref_index, jd_text)

    def _build_jd_section(self, jd_text: str | None) -> str:
        if not jd_text:
            return "（无 JD）"
        sanitized = self._sanitizer.sanitize(jd_text) or ""
        return self._sanitizer.wrap_with_delimiters("职位描述", sanitized)

    def _convert_to_questions(
        self,
        result: QuestionList,
        target_count: int,
    ) -> list[MainQuestionWithFollowUps]:
        items = result.questions[:target_count]
        return [
            (
                InterviewQuestion(
                    question_index=i,
                    question=item.question,
                    type=item.type,
                    category=item.category,
                    topic_summary=item.topicSummary,
                ),
                item.followUps,
            )
            for i, item in enumerate(items)
        ]

    def _merge_with_follow_ups(
        self,
        resume: list[MainQuestionWithFollowUps],
        direction: list[MainQuestionWithFollowUps],
        total: int,
    ) -> list[InterviewQuestion]:
        combined = list(resume) + list(direction)
        if len(combined) > total:
            combined = combined[:total]
        return self._attach(combined)

    def _cap_and_attach(
        self,
        items: list[MainQuestionWithFollowUps],
        total: int,
    ) -> list[InterviewQuestion]:
        return self._attach(items[:total])

    def _attach(self, items: list[MainQuestionWithFollowUps]) -> list[InterviewQuestion]:
        main_qs = [
            InterviewQuestion(
                question_index=i,
                question=q.question,
                type=q.type,
                category=q.category,
                topic_summary=q.topic_summary,
            )
            for i, (q, _) in enumerate(items)
        ]
        follow_up_map = {i: fus for i, (_, fus) in enumerate(items) if fus}
        return attach_follow_ups(main_qs, follow_up_map)
