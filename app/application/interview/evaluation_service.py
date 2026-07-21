"""面试评估读侧应用服务：查询评估结果 + 导出报告 PDF。

从 DB（session 聚合字段 + answers 逐题字段）重建 EvaluationReport，供 API 查询与 PDF 导出复用。
"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interview.schemas import (
    CategoryScoreDTO,
    EvaluationResultDTO,
    QuestionEvaluationDetailDTO,
    ReferenceAnswerDTO,
)
from app.domain.entities.evaluation import (
    EvaluationReport,
    QuestionEvaluation,
    ReferenceAnswer,
)
from app.domain.entities.interview import InterviewQuestion, SessionStatus
from app.domain.errors import BusinessException, ErrorCode
from app.domain.services.evaluation import compute_category_scores
from app.domain.services.question_codec import deserialize_questions
from app.infrastructure.db.models.interview import InterviewAnswer as InterviewAnswerORM
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM
from app.infrastructure.db.repositories.interview_repository import InterviewRepository
from app.infrastructure.export.pdf import PdfExportService
from app.infrastructure.json_utils import json_loads_dict_list, json_loads_list

logger = logging.getLogger(__name__)

_UNANSWERED_FEEDBACK = "该题未作答。"


class InterviewEvaluationService:
    """面试评估读侧服务：查询评估结果、导出报告。每个方法接收 AsyncSession（由 DI 注入）。"""

    def __init__(
        self,
        session: AsyncSession,
        repository: InterviewRepository,
        pdf_service: PdfExportService,
    ) -> None:
        self._session = session
        self._repository = repository
        self._pdf_service = pdf_service

    async def get_evaluation(self, session_id: str) -> EvaluationResultDTO:
        orm, answers = await self._load_evaluated(session_id)
        report = self._reconstruct_report(orm, answers)
        return self._to_dto(report, orm.evaluate_status or "")

    async def export_report(self, session_id: str) -> bytes:
        orm, answers = await self._load_evaluated(session_id)
        report = self._reconstruct_report(orm, answers)
        return await self._pdf_service.export_interview_report(orm, report)

    async def _load_evaluated(self, session_id: str) -> tuple[InterviewSessionORM, list[InterviewAnswerORM]]:
        orm = await self._repository.find_by_session_id(self._session, session_id)
        if orm is None:
            raise BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND)
        if orm.status != SessionStatus.EVALUATED.value:
            raise BusinessException(ErrorCode.INTERVIEW_EVALUATION_NOT_FOUND)
        answers = await self._repository.find_answers_by_session_id(self._session, orm.id)
        return orm, answers

    def _reconstruct_report(self, orm: InterviewSessionORM, answers: list[InterviewAnswerORM]) -> EvaluationReport:
        questions = self._parse_questions_safely(orm.questions_json, orm.session_id)
        if questions:
            answer_map = {a.question_index: a for a in answers}
            question_details = [self._build_question_evaluation(q, answer_map.get(q.question_index)) for q in questions]
        else:
            # questions_json 解析失败或为空时回退到 answers-only 模式，不丢失已答题数据
            question_details = [self._from_answer(a) for a in answers]
        category_scores = compute_category_scores(question_details)
        reference_answers = self._parse_reference_answers(orm.reference_answers_json)
        return EvaluationReport(
            session_id=orm.session_id,
            total_questions=orm.total_questions,
            overall_score=orm.overall_score or 0,
            category_scores=category_scores,
            question_details=question_details,
            overall_feedback=orm.overall_feedback or "",
            strengths=self._parse_list(orm.strengths_json),
            improvements=self._parse_list(orm.improvements_json),
            reference_answers=reference_answers,
        )

    @staticmethod
    def _parse_questions_safely(questions_json: str | None, session_id: str) -> list[InterviewQuestion]:
        """解析 questions_json，异常时回退为空列表（上层回退到 answers-only 模式）。"""
        if not questions_json:
            return []
        try:
            return deserialize_questions(questions_json)
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("questions_json 解析失败，回退到 answers-only 模式: sessionId=%s", session_id)
            return []

    @staticmethod
    def _from_answer(ans: InterviewAnswerORM) -> QuestionEvaluation:
        """从 answer 行重建 QuestionEvaluation（fallback 与已答题路径共用）。"""
        return QuestionEvaluation(
            question_index=ans.question_index,
            question=ans.question or "",
            category=ans.category or "",
            user_answer=ans.user_answer,
            score=ans.score or 0,
            feedback=ans.feedback or "",
        )

    @staticmethod
    def _build_question_evaluation(
        q: InterviewQuestion,
        ans: InterviewAnswerORM | None,
    ) -> QuestionEvaluation:
        """已答题从 answer 行重建；未回答题补齐为 score=0/user_answer=None/未作答文案。"""
        if ans is not None:
            return InterviewEvaluationService._from_answer(ans)
        return QuestionEvaluation(
            question_index=q.question_index,
            question=q.question,
            category=q.category,
            user_answer=None,
            score=0,
            feedback=_UNANSWERED_FEEDBACK,
        )

    @staticmethod
    def _parse_reference_answers(raw: str | None) -> list[ReferenceAnswer]:
        items = json_loads_dict_list(raw)
        result: list[ReferenceAnswer] = []
        for item in items:
            result.append(
                ReferenceAnswer(
                    question_index=int(item.get("questionIndex", 0)),
                    question=str(item.get("question", "")),
                    reference_answer=str(item.get("referenceAnswer", "")),
                    key_points=list(item.get("keyPoints", [])),
                )
            )
        return result

    @staticmethod
    def _parse_list(raw: str | None) -> list[str]:
        return [str(s) for s in json_loads_list(raw)]

    @staticmethod
    def _to_dto(report: EvaluationReport, evaluate_status: str) -> EvaluationResultDTO:
        return EvaluationResultDTO(
            session_id=report.session_id,
            total_questions=report.total_questions,
            overall_score=report.overall_score,
            overall_feedback=report.overall_feedback,
            category_scores=[
                CategoryScoreDTO(category=c.category, score=c.score, question_count=c.question_count)
                for c in report.category_scores
            ],
            question_details=[
                QuestionEvaluationDetailDTO(
                    question_index=d.question_index,
                    question=d.question,
                    category=d.category,
                    user_answer=d.user_answer,
                    score=d.score,
                    feedback=d.feedback,
                )
                for d in report.question_details
            ],
            strengths=report.strengths,
            improvements=report.improvements,
            reference_answers=[
                ReferenceAnswerDTO(
                    question_index=r.question_index,
                    question=r.question,
                    reference_answer=r.reference_answer,
                    key_points=list(r.key_points),
                )
                for r in report.reference_answers
            ],
            evaluate_status=evaluate_status,
        )
