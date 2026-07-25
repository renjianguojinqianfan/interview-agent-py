"""知识库题库应用服务：题目 CRUD / 筛选 / 方向统计（对齐 Java KnowledgeBaseQuestionService，issue #42）。"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.knowledgebase.question_schemas import (
    CategoryCountDTO,
    CreateKnowledgeBaseQuestionRequest,
    KnowledgeBaseQuestionDTO,
    KnowledgeBaseQuestionFollowUpDTO,
    UpdateKnowledgeBaseQuestionRequest,
)
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase, KnowledgeBaseQuestion
from app.infrastructure.db.repositories.knowledge_base_question_repository import KnowledgeBaseQuestionRepository
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.json_utils import json_loads_dict_list, json_loads_list

logger = logging.getLogger(__name__)

# 知识库题目固定 skill_id：兼容既有面试会话表的非空约束（对齐 Java DEFAULT_SKILL_ID）
DEFAULT_SKILL_ID = "knowledge-base"
_DEFAULT_DIFFICULTY = "mid"
# keyword 匹配的字段集合（对齐 Java containsKeyword）
_KEYWORD_FIELDS = ("question", "reference_answer", "scoring_rubric", "topic_summary", "category")


def _trim_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _require_non_blank(value: str | None, message: str) -> str:
    """必填文本校验：空白拒绝（对齐 Java @NotBlank / isBlank 检查），返回 trim 后的值。"""
    trimmed = _trim_to_none(value)
    if trimmed is None:
        raise BusinessException(ErrorCode.BAD_REQUEST, message)
    return trimmed


def _normalize_difficulty(difficulty: str | None) -> str:
    return difficulty.strip() if difficulty and difficulty.strip() else _DEFAULT_DIFFICULTY


def _write_string_list(values: list[str] | None) -> str:
    """要点列表 -> JSON 文本：去空白项 + trim（对齐 Java writeStringList）。"""
    sanitized = [value.strip() for value in (values or []) if value and value.strip()]
    return json.dumps(sanitized, ensure_ascii=False)


def _write_follow_ups(values: list[KnowledgeBaseQuestionFollowUpDTO] | None) -> str:
    """追问列表 -> JSON 文本（camelCase 键）：丢弃空题干项、字段 trim（对齐 Java writeFollowUps）。"""
    sanitized = [
        KnowledgeBaseQuestionFollowUpDTO(
            question=item.question.strip(),
            reference_answer=_trim_to_none(item.reference_answer),
            key_points=[point.strip() for point in item.key_points if point and point.strip()],
            scoring_rubric=_trim_to_none(item.scoring_rubric),
        )
        for item in (values or [])
        if item.question and item.question.strip()
    ]
    return json.dumps([item.model_dump(by_alias=True) for item in sanitized], ensure_ascii=False)


class KnowledgeBaseQuestionService:
    """题库管理编排：列表筛选、方向计数、手动新增、编辑、上下架、删除。"""

    def __init__(
        self,
        session: AsyncSession,
        question_repository: KnowledgeBaseQuestionRepository,
        kb_repository: KnowledgeBaseRepository,
    ) -> None:
        self._session = session
        self._question_repository = question_repository
        self._kb_repository = kb_repository

    async def list_questions(
        self,
        kb_id: int,
        status: str | None,
        category: str | None,
        difficulty: str | None,
        keyword: str | None,
    ) -> list[KnowledgeBaseQuestionDTO]:
        questions = await self._question_repository.list_by_knowledge_base(self._session, kb_id, status=status)
        category_filter = _trim_to_none(category)
        difficulty_filter = _trim_to_none(difficulty)
        keyword_filter = _trim_to_none(keyword)
        kb = await self._kb_repository.get_by_id(self._session, kb_id)
        kb_name = self._kb_name(kb)
        return [
            self._to_dto(q, kb_name)
            for q in questions
            if (category_filter is None or q.category == category_filter)
            and (difficulty_filter is None or q.difficulty == difficulty_filter)
            and (keyword_filter is None or self._contains_keyword(q, keyword_filter))
        ]

    async def list_categories(self, kb_id: int) -> list[CategoryCountDTO]:
        counts = await self._question_repository.category_counts(self._session, kb_id)
        return [CategoryCountDTO(category=category, count=count) for category, count in counts]

    async def create_question(
        self, kb_id: int, request: CreateKnowledgeBaseQuestionRequest
    ) -> KnowledgeBaseQuestionDTO:
        kb = await self._kb_repository.get_by_id(self._session, kb_id)
        if kb is None:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)
        category = _require_non_blank(request.category, "面试方向不能为空")
        question_text = _require_non_blank(request.question, "题干不能为空")

        now = datetime.now(UTC)  # 应用侧时间戳，对齐 Java @PrePersist（server_default 仅为迁移兼容）
        question = KnowledgeBaseQuestion(
            knowledge_base_id=kb.id,
            skill_id=DEFAULT_SKILL_ID,
            difficulty=_normalize_difficulty(request.difficulty),
            type=_trim_to_none(request.type),
            category=category,
            question=question_text,
            topic_summary=_trim_to_none(request.topic_summary),
            reference_answer=_trim_to_none(request.reference_answer),
            key_points_json=_write_string_list(request.key_points),
            scoring_rubric=_trim_to_none(request.scoring_rubric),
            follow_ups_json=_write_follow_ups(request.follow_ups),
            source_context=_trim_to_none(request.source_context),
            kb_content_hash=kb.file_hash,
            status=request.status or "DRAFT",
            created_at=now,
            updated_at=now,
        )
        await self._question_repository.save(self._session, question)
        await self._session.commit()
        logger.info("手动新增题库题目: knowledgeBaseId=%s, questionId=%s", kb_id, question.id)
        return self._to_dto(question, self._kb_name(kb))

    async def update_question(
        self, question_id: int, request: UpdateKnowledgeBaseQuestionRequest
    ) -> KnowledgeBaseQuestionDTO:
        question = await self._get_question(question_id)
        if request.difficulty is not None:
            question.difficulty = _normalize_difficulty(request.difficulty)
        if request.type is not None:
            question.type = _trim_to_none(request.type)
        if request.category is not None:
            question.category = _require_non_blank(request.category, "面试方向不能为空")
        if request.question is not None:
            question.question = _require_non_blank(request.question, "题干不能为空")
        if request.topic_summary is not None:
            question.topic_summary = _trim_to_none(request.topic_summary)
        if request.reference_answer is not None:
            question.reference_answer = _trim_to_none(request.reference_answer)
        if request.key_points is not None:
            question.key_points_json = _write_string_list(request.key_points)
        if request.scoring_rubric is not None:
            question.scoring_rubric = _trim_to_none(request.scoring_rubric)
        if request.follow_ups is not None:
            question.follow_ups_json = _write_follow_ups(request.follow_ups)
        if request.source_context is not None:
            question.source_context = _trim_to_none(request.source_context)
        if request.status is not None:
            question.status = request.status
        question.updated_at = datetime.now(UTC)
        await self._question_repository.save(self._session, question)
        await self._session.commit()
        return await self._to_dto_with_kb(question)

    async def update_status(self, question_id: int, status: str) -> KnowledgeBaseQuestionDTO:
        question = await self._get_question(question_id)
        question.status = status
        question.updated_at = datetime.now(UTC)
        await self._question_repository.save(self._session, question)
        await self._session.commit()
        logger.info("题目状态切换: questionId=%s, status=%s", question_id, status)
        return await self._to_dto_with_kb(question)

    async def delete_question(self, question_id: int) -> None:
        question = await self._get_question(question_id)
        await self._question_repository.delete(self._session, question)
        await self._session.commit()
        logger.info("题目已删除: questionId=%s", question_id)

    async def _get_question(self, question_id: int) -> KnowledgeBaseQuestion:
        question = await self._question_repository.get_by_id(self._session, question_id)
        if question is None:
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND)
        return question

    async def _to_dto_with_kb(self, question: KnowledgeBaseQuestion) -> KnowledgeBaseQuestionDTO:
        kb = await self._kb_repository.get_by_id(self._session, question.knowledge_base_id)
        return self._to_dto(question, self._kb_name(kb))

    def _kb_name(self, kb: KnowledgeBase | None) -> str | None:
        if kb is None:
            return None
        return kb.name or kb.original_filename

    def _contains_keyword(self, question: KnowledgeBaseQuestion, keyword: str) -> bool:
        lower = keyword.lower()
        return any(
            value is not None and lower in value.lower()
            for value in (getattr(question, field) for field in _KEYWORD_FIELDS)
        )

    def _to_dto(self, question: KnowledgeBaseQuestion, kb_name: str | None) -> KnowledgeBaseQuestionDTO:
        return KnowledgeBaseQuestionDTO(
            id=question.id,
            knowledge_base_id=question.knowledge_base_id,
            knowledge_base_name=kb_name,
            skill_id=question.skill_id,
            difficulty=question.difficulty,
            type=question.type,
            category=question.category,
            question=question.question,
            topic_summary=question.topic_summary,
            reference_answer=question.reference_answer,
            key_points=[str(item) for item in json_loads_list(question.key_points_json)],
            scoring_rubric=question.scoring_rubric,
            follow_ups=[
                KnowledgeBaseQuestionFollowUpDTO.model_validate(item)
                for item in json_loads_dict_list(question.follow_ups_json)
            ],
            source_context=question.source_context,
            status=question.status,
            created_at=question.created_at,
            updated_at=question.updated_at,
        )
