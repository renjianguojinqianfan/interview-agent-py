"""面试评估读侧服务单元测试：mock 仓储，验证 DB->DTO 重建逻辑。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.interview.evaluation_service import InterviewEvaluationService
from app.domain.entities.interview import SessionStatus
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.interview import InterviewAnswer as InterviewAnswerORM
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM


def _make_session_orm(**overrides: object) -> InterviewSessionORM:
    defaults: dict[str, object] = {
        "id": 1,
        "session_id": "sess123",
        "skill_id": "java-backend",
        "difficulty": "mid",
        "total_questions": 2,
        "current_question_index": 2,
        "status": SessionStatus.EVALUATED.value,
        "overall_score": 80,
        "overall_feedback": "整体良好",
        "strengths_json": json.dumps(["基础扎实"], ensure_ascii=False),
        "improvements_json": json.dumps(["需补深度"], ensure_ascii=False),
        "reference_answers_json": json.dumps(
            [{"questionIndex": 0, "question": "Q1", "referenceAnswer": "参考1", "keyPoints": ["要点1"]}],
            ensure_ascii=False,
        ),
        "evaluate_status": "COMPLETED",
    }
    defaults.update(overrides)
    return InterviewSessionORM(**defaults)  # type: ignore[arg-type]


def _make_answer_orm(index: int, score: int, category: str = "Java") -> InterviewAnswerORM:
    return InterviewAnswerORM(
        id=index + 1,
        session_id=1,
        question_index=index,
        question=f"Q{index}",
        category=category,
        user_answer=f"A{index}",
        score=score,
        feedback="反馈",
        reference_answer="参考",
        key_points_json='["要点"]',
    )


def _make_service(
    session_orm: InterviewSessionORM | None = None,
    answers: list[InterviewAnswerORM] | None = None,
) -> tuple[InterviewEvaluationService, MagicMock]:
    session = MagicMock()
    repository = MagicMock()
    repository.find_by_session_id = AsyncMock(return_value=session_orm)
    repository.find_answers_by_session_id = AsyncMock(return_value=answers or [])
    pdf_service = MagicMock()
    pdf_service.export_interview_report = AsyncMock(return_value=b"%PDF-1.4")
    service = InterviewEvaluationService(session=session, repository=repository, pdf_service=pdf_service)
    return service, repository


class TestGetEvaluation:
    async def test_reconstructs_dto_from_db(self) -> None:
        orm = _make_session_orm()
        answers = [_make_answer_orm(0, 90), _make_answer_orm(1, 70)]
        service, _ = _make_service(session_orm=orm, answers=answers)

        dto = await service.get_evaluation("sess123")

        assert dto.session_id == "sess123"
        assert dto.overall_score == 80
        assert dto.overall_feedback == "整体良好"
        assert dto.strengths == ["基础扎实"]
        assert dto.improvements == ["需补深度"]
        assert len(dto.question_details) == 2
        assert dto.question_details[0].score == 90
        # 分类得分由 answers 计算：(90+70)/2=80
        assert dto.category_scores[0].score == 80
        assert dto.category_scores[0].question_count == 2
        # 参考答案从 session.reference_answers_json 重建
        assert dto.reference_answers[0].reference_answer == "参考1"
        assert dto.reference_answers[0].key_points == ["要点1"]

    async def test_raises_not_found_when_session_missing(self) -> None:
        service, _ = _make_service(session_orm=None)
        with pytest.raises(BusinessException) as exc:
            await service.get_evaluation("missing")
        assert exc.value.error_code == ErrorCode.INTERVIEW_SESSION_NOT_FOUND

    async def test_raises_evaluation_not_found_when_not_evaluated(self) -> None:
        orm = _make_session_orm(status=SessionStatus.COMPLETED.value)
        service, _ = _make_service(session_orm=orm)
        with pytest.raises(BusinessException) as exc:
            await service.get_evaluation("sess123")
        assert exc.value.error_code == ErrorCode.INTERVIEW_EVALUATION_NOT_FOUND

    async def test_category_scores_grouped_by_category(self) -> None:
        orm = _make_session_orm()
        answers = [_make_answer_orm(0, 80, "Java"), _make_answer_orm(1, 60, "MySQL")]
        service, _ = _make_service(session_orm=orm, answers=answers)

        dto = await service.get_evaluation("sess123")

        cat_map = {c.category: c for c in dto.category_scores}
        assert cat_map["Java"].score == 80
        assert cat_map["MySQL"].score == 60


class TestExportReport:
    async def test_calls_pdf_service_with_reconstructed_report(self) -> None:
        orm = _make_session_orm()
        answers = [_make_answer_orm(0, 90), _make_answer_orm(1, 70)]
        service, repository = _make_service(session_orm=orm, answers=answers)

        result = await service.export_report("sess123")

        assert result == b"%PDF-1.4"
        # 验证 pdf_service 被调用，且传入的 report 总分来自 session
        service._pdf_service.export_interview_report.assert_awaited_once()
        call_args = service._pdf_service.export_interview_report.call_args
        passed_orm = call_args.args[0]
        passed_report = call_args.args[1]
        assert passed_orm is orm
        assert passed_report.overall_score == 80
        assert len(passed_report.question_details) == 2

    async def test_raises_evaluation_not_found_when_not_evaluated(self) -> None:
        orm = _make_session_orm(status=SessionStatus.COMPLETED.value)
        service, _ = _make_service(session_orm=orm)
        with pytest.raises(BusinessException) as exc:
            await service.export_report("sess123")
        assert exc.value.error_code == ErrorCode.INTERVIEW_EVALUATION_NOT_FOUND
