"""知识库组卷面试应用服务：容量预检 + 从 ACTIVE 题库随机组卷建会（对齐 Java KnowledgeBaseInterviewService，issue #44）。

组卷/容量算法在 domain/services/question_bank（随机源注入可复现）；
本服务负责查询候选、JSON 解析清洗与委托 InterviewSessionService 建会。
"""

import logging
from random import Random

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interview.schemas import InterviewSessionDTO
from app.application.interview.session_service import InterviewSessionService
from app.application.knowledgebase.question_schemas import (
    CreateKnowledgeBaseInterviewRequest,
    InterviewCategoryOptionDTO,
    InterviewFollowUpOptionDTO,
    KnowledgeBaseInterviewCapacityResponse,
)
from app.domain.entities.interview import DEFAULT_DIFFICULTY
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.question_bank import (
    QuestionBankFollowUp,
    QuestionCandidate,
    assemble_interview_questions,
    calculate_interview_capacity,
    trim_to_none,
)
from app.infrastructure.db.models.knowledge_base import KnowledgeBaseQuestion
from app.infrastructure.db.repositories.knowledge_base_question_repository import KnowledgeBaseQuestionRepository
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.json_utils import json_loads_dict_list, json_loads_list

logger = logging.getLogger(__name__)

# 知识库面试固定 skill_id（同题库，skillId 已无业务含义，统一回填面试会话表）
_KB_INTERVIEW_SKILL_ID = "knowledge-base"


class KnowledgeBaseInterviewService:
    """知识库组卷面试服务：capacity 预检 / 组卷建会。"""

    def __init__(
        self,
        session: AsyncSession,
        question_repository: KnowledgeBaseQuestionRepository,
        kb_repository: KnowledgeBaseRepository,
        interview_session_service: InterviewSessionService,
        rng: Random | None = None,
    ) -> None:
        self._session = session
        self._question_repository = question_repository
        self._kb_repository = kb_repository
        self._interview_session_service = interview_session_service
        self._rng = rng if rng is not None else Random()  # noqa: S311  组卷洗牌非密码学用途

    async def create_session(self, request: CreateKnowledgeBaseInterviewRequest) -> InterviewSessionDTO:
        """从 ACTIVE 题目随机组卷并建会；候选不足抛 INTERVIEW_QUESTION_INSUFFICIENT。"""
        await self._require_kb(request.knowledge_base_id)
        category = trim_to_none(request.category)
        difficulty = _normalize_difficulty(request.difficulty)

        rows = await self._question_repository.find_active_questions(
            self._session,
            kb_id=request.knowledge_base_id,
            difficulty=difficulty,
            category=category,
        )
        questions = assemble_interview_questions(
            [self._to_candidate(row) for row in rows],
            request.main_question_count,
            request.follow_up_count,
            self._rng,
            difficulty,
            category=category,
        )

        logger.info(
            "创建知识库面试: kbId=%s, category=%s, difficulty=%s, mainQuestions=%s, totalQuestions=%s",
            request.knowledge_base_id,
            category,
            difficulty,
            request.main_question_count,
            len(questions),
        )
        return await self._interview_session_service.create_session_from_questions(
            questions=questions,
            llm_provider=request.llm_provider,
            skill_id=_KB_INTERVIEW_SKILL_ID,
            difficulty=difficulty,
            knowledge_base_id=request.knowledge_base_id,
            interview_category=category,
        )

    async def get_capacity(
        self,
        kb_id: int,
        category: str | None,
        difficulty: str | None,
        main_question_count: int,
    ) -> KnowledgeBaseInterviewCapacityResponse:
        """容量预检：全方向计数 + 0~5 追问档位可行性（category 过滤在 domain scoped 内完成）。"""
        await self._require_kb(kb_id)
        normalized_category = trim_to_none(category)
        normalized_difficulty = _normalize_difficulty(difficulty)

        rows = await self._question_repository.find_active_questions(
            self._session,
            kb_id=kb_id,
            difficulty=normalized_difficulty,
            category=None,
        )
        categories, follow_up_options = calculate_interview_capacity(
            [self._to_candidate(row) for row in rows],
            normalized_category,
            main_question_count,
        )
        return KnowledgeBaseInterviewCapacityResponse(
            knowledge_base_id=kb_id,
            category=normalized_category,
            difficulty=normalized_difficulty,
            main_question_count=main_question_count,
            categories=[
                InterviewCategoryOptionDTO(
                    category=option.category,
                    available_question_count=option.available_question_count,
                )
                for option in categories
            ],
            follow_up_options=[
                InterviewFollowUpOptionDTO(
                    follow_up_count=option.follow_up_count,
                    available_question_count=option.available_question_count,
                    selectable=option.selectable,
                )
                for option in follow_up_options
            ],
        )

    async def _require_kb(self, kb_id: int) -> None:
        kb = await self._kb_repository.get_by_id(self._session, kb_id)
        if kb is None:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)

    def _to_candidate(self, row: KnowledgeBaseQuestion) -> QuestionCandidate:
        return QuestionCandidate(
            question=row.question,
            type=row.type,
            category=row.category,
            topic_summary=row.topic_summary,
            reference_answer=row.reference_answer,
            key_points=[str(p) for p in json_loads_list(row.key_points_json)],
            scoring_rubric=row.scoring_rubric,
            source_context=row.source_context,
            follow_ups=self._parse_usable_follow_ups(row.follow_ups_json),
        )

    @staticmethod
    def _parse_usable_follow_ups(raw: str | None) -> list[QuestionBankFollowUp]:
        """解析追问池并清洗：过滤空题干、题干 trim（对齐 Java readUsableFollowUps）。"""
        follow_ups: list[QuestionBankFollowUp] = []
        for item in json_loads_dict_list(raw):
            question = trim_to_none(str(item.get("question") or ""))
            if question is None:
                continue
            reference_answer = item.get("referenceAnswer")
            scoring_rubric = item.get("scoringRubric")
            follow_ups.append(
                QuestionBankFollowUp(
                    question=question,
                    reference_answer=str(reference_answer) if reference_answer is not None else None,
                    key_points=[str(p) for p in item.get("keyPoints") or []],
                    scoring_rubric=str(scoring_rubric) if scoring_rubric is not None else None,
                )
            )
        return follow_ups


def _normalize_difficulty(difficulty: str | None) -> str:
    from app.domain.entities.interview import VALID_DIFFICULTIES

    trimmed = trim_to_none(difficulty) or DEFAULT_DIFFICULTY
    if trimmed not in VALID_DIFFICULTIES:
        logger.warning("非标准难度值 %r，回退为 %r", trimmed, DEFAULT_DIFFICULTY)
        return DEFAULT_DIFFICULTY
    return trimmed
