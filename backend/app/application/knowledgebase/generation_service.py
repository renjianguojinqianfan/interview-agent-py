"""知识库题库异步生成服务（对齐 Java KnowledgeBaseQuestionGenerationService）。

由 QuestionGenStreamConsumer 调用。LLM 调用不在事务内；
删除旧题 + 保存新题 + 置 COMPLETED 在 state_service 的同一个小事务中完成。
"""

import json
import logging

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.knowledgebase.generation_state_service import QuestionGenerationStateService
from app.application.knowledgebase.question_schemas import (
    KnowledgeBaseQuestionFollowUpDTO,
    QuestionGenerationConfigDTO,
)
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.question_bank import normalize_question_key, trim_to_none
from app.infrastructure.ai.llm_registry import LlmProviderRegistry
from app.infrastructure.ai.prompt_constants import DATA_BOUNDARY_INSTRUCTION
from app.infrastructure.ai.prompt_loader import load_prompt
from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer
from app.infrastructure.ai.structured_output import StructuredOutputInvoker
from app.infrastructure.db.models.knowledge_base import KnowledgeBase, KnowledgeBaseQuestion
from app.infrastructure.db.repositories.knowledge_base_document_repository import KnowledgeBaseDocumentRepository
from app.infrastructure.db.repositories.knowledge_base_question_repository import KnowledgeBaseQuestionRepository
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.vector.repository import VectorRepository

logger = logging.getLogger(__name__)

_RETRIEVAL_TOP_K = 12
_RETRIEVAL_QUERY_TOP_K = 4
_MAX_CONTEXT_CHARS = 5000
_EXISTING_CATEGORY_LIMIT = 10
_RECENT_QUESTION_LIMIT = 20
_DEFAULT_SKILL_ID = "knowledge-base"

# 固定检索查询词组：覆盖概念/流程/约束/案例四个出题维度（对齐 Java buildGenerationQueries）
_GENERATION_QUERIES = (
    "核心概念 定义 背景 原理",
    "关键流程 步骤 方法 工作机制",
    "规则约束 条件 边界 例外 限制",
    "典型案例 常见问题 应用场景 最佳实践",
)


class GeneratedQuestion(BaseModel):
    """LLM 单题输出（camelCase 字段对齐提示词输出要求，惯例同 graphs/evaluation.py）。"""

    category: str | None = None
    type: str | None = None
    question: str | None = None
    topicSummary: str | None = None  # noqa: N815
    referenceAnswer: str | None = None  # noqa: N815
    keyPoints: list[str] = Field(default_factory=list)  # noqa: N815
    scoringRubric: str | None = None  # noqa: N815
    followUps: list[KnowledgeBaseQuestionFollowUpDTO] = Field(default_factory=list)  # noqa: N815


class GeneratedQuestionList(BaseModel):
    """LLM 出题批次输出。"""

    questions: list[GeneratedQuestion] = Field(default_factory=list)


class _GenerationBatch:
    def __init__(self, questions: list[KnowledgeBaseQuestion], skipped_count: int) -> None:
        self.questions = questions
        self.skipped_count = skipped_count


class QuestionGenerationService:
    """执行题库生成：校验 -> 检索上下文 -> LLM 结构化出题 -> 去重构建实体 -> 小事务替换落库。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        kb_repository: KnowledgeBaseRepository,
        question_repository: KnowledgeBaseQuestionRepository,
        vector_repository: VectorRepository,
        llm_registry: LlmProviderRegistry,
        invoker: StructuredOutputInvoker,
        state_service: QuestionGenerationStateService,
        document_repository: KnowledgeBaseDocumentRepository,
        sanitizer: PromptSanitizer | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._kb_repository = kb_repository
        self._question_repository = question_repository
        self._vector_repository = vector_repository
        self._llm_registry = llm_registry
        self._invoker = invoker
        self._state_service = state_service
        self._sanitizer = sanitizer or PromptSanitizer()
        self._document_repository = document_repository

    async def execute_generation(self, kb_id: int, task_id: str, config: QuestionGenerationConfigDTO) -> None:
        async with self._session_factory() as session:
            kb = await self._kb_repository.get_by_id(session, kb_id)
            if kb is None:
                raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)
            # 再次确认任务 ID 匹配（旧任务消息不落库）
            if kb.question_gen_task_id != task_id:
                logger.info(
                    "任务ID不匹配，放弃生成: kbId=%s, msgTaskId=%s, currentTaskId=%s",
                    kb_id,
                    task_id,
                    kb.question_gen_task_id,
                )
                return
            existing_categories = await self._build_existing_category_section(session, kb_id)

        difficulty = config.difficulty.strip() if config.difficulty and config.difficulty.strip() else "mid"
        # 入口已校验/归一化，此处 clamp 为旧快照数据兜底（对齐 Java executeGeneration 再次收敛）
        normalized = QuestionGenerationConfigDTO(
            difficulty=difficulty,
            question_count=max(1, config.question_count),
            follow_up_count=max(0, min(config.follow_up_count, 5)),
            category_limit=max(1, min(config.category_limit, 5)),
            llm_provider=config.llm_provider,
        )

        # 1. 检索上下文 + 已有题目（不在事务中）
        context = await self._build_generation_context(kb_id)
        async with self._session_factory() as session:
            existing_questions = await self._build_existing_question_section(session, kb_id, difficulty)

        # 2. 调用 LLM（不在事务中）；供应商按名解析（不存在则抛 PROVIDER_NOT_FOUND，非静默回退）
        provider_id = None
        if config.llm_provider:
            provider_id = await self._llm_registry.resolve_provider_id_by_name(config.llm_provider)
        generated = await self._call_llm(kb, provider_id, normalized, context, existing_categories, existing_questions)
        if not generated.questions:
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED, "知识库题库生成结果为空")

        # 3. 构建实体（题干归一化去重，跳过计数）
        async with self._session_factory() as session:
            first_doc_hash = await self._document_repository.find_first_hash_by_kb(session, kb.id)
        batch = self._build_entities(kb, difficulty, context, normalized.follow_up_count, generated, first_doc_hash)
        if not batch.questions:
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED, "知识库题库生成结果无有效题干")

        # 4. 小事务：校验当前任务、整体替换题库并置 COMPLETED
        completed = await self._state_service.replace_questions_and_complete(
            kb_id, task_id, batch.questions, batch.skipped_count
        )
        if not completed:
            logger.info("题目生成任务已被替换，丢弃旧结果: kbId=%s, taskId=%s", kb_id, task_id)
            return
        logger.info("知识库题目异步生成完成: kbId=%s, taskId=%s, count=%d", kb_id, task_id, len(batch.questions))

    async def _build_generation_context(self, kb_id: int) -> str:
        embeddings = await self._llm_registry.get_default_embeddings()
        chunks: list[str] = []
        seen: set[str] = set()
        for query in _GENERATION_QUERIES:
            vector = await embeddings.aembed_query(query)
            async with self._session_factory() as session:
                hits = await self._vector_repository.search(session, vector, [kb_id], _RETRIEVAL_QUERY_TOP_K)
            for hit in hits:
                text = (hit.content or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                chunks.append(text)
                if len(chunks) >= _RETRIEVAL_TOP_K:
                    break
            if len(chunks) >= _RETRIEVAL_TOP_K:
                break
        if not chunks:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_QUERY_FAILED, "知识库未检索到可用于生成题目的内容")
        context = "\n\n---\n\n".join(chunks)
        if len(context) > _MAX_CONTEXT_CHARS:
            context = context[:_MAX_CONTEXT_CHARS] + "\n...(知识库片段过长，已截断)"
        return context

    async def _build_existing_category_section(self, session: AsyncSession, kb_id: int) -> str:
        counts = await self._question_repository.category_counts(session, kb_id)
        if not counts:
            return "暂无已有方向"
        return "\n".join(f"- {category}（{count} 题）" for category, count in counts[:_EXISTING_CATEGORY_LIMIT])

    async def _build_existing_question_section(self, session: AsyncSession, kb_id: int, difficulty: str) -> str:
        questions = await self._question_repository.find_recent_questions(
            session, kb_id, difficulty, limit=_RECENT_QUESTION_LIMIT
        )
        lines = [f"- {q.question.strip()}" for q in questions if q.question and q.question.strip()]
        return "\n".join(lines) if lines else "暂无已有题目"

    async def _call_llm(
        self,
        kb: KnowledgeBase,
        provider_id: int | None,
        config: QuestionGenerationConfigDTO,
        context: str,
        existing_categories: str,
        existing_questions: str,
    ) -> GeneratedQuestionList:
        system_template = await load_prompt("knowledgebase-question-generation-system")
        user_template = await load_prompt("knowledgebase-question-generation-user")
        system_prompt = system_template.format()
        user_prompt = user_template.format(
            knowledgeBaseName=self._sanitizer.sanitize(kb.name or kb.original_filename) or "",
            difficulty=config.difficulty,
            questionCount=config.question_count,
            followUpCount=config.follow_up_count,
            categoryLimit=config.category_limit,
            existingCategories=self._sanitizer.sanitize(existing_categories) or "",
            existingQuestions=self._sanitizer.sanitize(existing_questions) or "",
            context=DATA_BOUNDARY_INSTRUCTION
            + "\n"
            + self._sanitizer.wrap_with_delimiters("knowledge-base", self._sanitizer.sanitize(context) or ""),
        )
        llm = await self._llm_registry.get_plain_chat_client(provider_id)
        return await self._invoker.invoke(
            llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=GeneratedQuestionList,
            error_code=ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED,
            error_prefix="知识库题库生成失败：",
            log_context="知识库题库生成",
        )

    def _build_entities(
        self,
        kb: KnowledgeBase,
        difficulty: str,
        source_context: str,
        follow_up_count: int,
        generated: GeneratedQuestionList,
        kb_content_hash: str | None,
    ) -> _GenerationBatch:
        entities: list[KnowledgeBaseQuestion] = []
        batch_keys: set[str] = set()
        skipped_count = 0
        kb_name = kb.name or kb.original_filename
        for dto in generated.questions:
            raw_question = (dto.question or "").strip()
            if not raw_question:
                skipped_count += 1
                continue
            key = normalize_question_key(raw_question)
            if key in batch_keys:
                skipped_count += 1
                continue
            batch_keys.add(key)
            category = trim_to_none(dto.category) or (kb_name.strip() if kb_name and kb_name.strip() else "未分类")
            entities.append(
                KnowledgeBaseQuestion(
                    knowledge_base_id=kb.id,
                    skill_id=_DEFAULT_SKILL_ID,
                    difficulty=difficulty,
                    type=trim_to_none(dto.type),
                    category=category,
                    question=raw_question,
                    topic_summary=trim_to_none(dto.topicSummary),
                    reference_answer=trim_to_none(dto.referenceAnswer),
                    key_points_json=self._write_string_list(dto.keyPoints),
                    scoring_rubric=trim_to_none(dto.scoringRubric),
                    follow_ups_json=self._write_follow_ups(dto.followUps, follow_up_count),
                    source_context=source_context,
                    kb_content_hash=kb_content_hash,
                    status="DRAFT",
                )
            )
        return _GenerationBatch(entities, skipped_count)

    def _write_string_list(self, values: list[str]) -> str:
        sanitized = [value.strip() for value in values if value and value.strip()]
        return json.dumps(sanitized, ensure_ascii=False)

    def _write_follow_ups(self, values: list[KnowledgeBaseQuestionFollowUpDTO], follow_up_count: int) -> str:
        sanitized = [
            KnowledgeBaseQuestionFollowUpDTO(
                question=item.question.strip(),
                reference_answer=trim_to_none(item.reference_answer),
                key_points=[point.strip() for point in item.key_points if point and point.strip()],
                scoring_rubric=trim_to_none(item.scoring_rubric),
            )
            for item in values
            if item.question and item.question.strip()
        ][:follow_up_count]
        return json.dumps([item.model_dump(by_alias=True) for item in sanitized], ensure_ascii=False)
