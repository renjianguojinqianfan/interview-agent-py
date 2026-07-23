"""面试评估读侧服务单元测试：mock 仓储，验证 DB->DTO 重建逻辑。"""

import json
from datetime import UTC, datetime
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
        "questions_json": json.dumps(
            [
                {
                    "questionIndex": 0,
                    "question": "Q0",
                    "type": "short",
                    "category": "Java",
                    "topicSummary": None,
                    "userAnswer": None,
                    "score": None,
                    "feedback": None,
                    "isFollowUp": False,
                    "parentQuestionIndex": None,
                },
                {
                    "questionIndex": 1,
                    "question": "Q1",
                    "type": "short",
                    "category": "Java",
                    "topicSummary": None,
                    "userAnswer": None,
                    "score": None,
                    "feedback": None,
                    "isFollowUp": False,
                    "parentQuestionIndex": None,
                },
            ],
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
        answered_at=datetime(2026, 7, 20, 9, 0, 0, tzinfo=UTC),
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

    async def test_unanswered_questions_backfilled_from_questions_json(self) -> None:
        """未回答题从 questions_json 补齐：score=0/user_answer=None/feedback=未作答文案。

        验证 R3 review finding (c).1 修复：read 侧 _reconstruct_report 从 questions_json
        补齐未回答题，question_details 数 == total_questions，违反 #9 逐题反馈验收。
        """
        questions_json = json.dumps(
            [
                {
                    "questionIndex": i,
                    "question": f"Q{i}",
                    "type": "short",
                    "category": "Java",
                    "topicSummary": None,
                    "userAnswer": None,
                    "score": None,
                    "feedback": None,
                    "isFollowUp": False,
                    "parentQuestionIndex": None,
                }
                for i in range(3)
            ],
            ensure_ascii=False,
        )
        orm = _make_session_orm(total_questions=3, questions_json=questions_json)
        answers = [_make_answer_orm(0, 90), _make_answer_orm(2, 70)]  # Q1 未回答
        service, _ = _make_service(session_orm=orm, answers=answers)

        dto = await service.get_evaluation("sess123")

        # 未回答题补齐：question_details 数 == total_questions
        assert len(dto.question_details) == 3
        # Q1 未回答：score=0/user_answer=None/feedback=未作答文案
        q1 = next(d for d in dto.question_details if d.question_index == 1)
        assert q1.user_answer is None
        assert q1.score == 0
        assert q1.feedback == "该题未作答。"
        # 分类得分仅计已答题（Q0=90 + Q2=70）/2 = 80，Q1 不在分母
        assert len(dto.category_scores) == 1
        assert dto.category_scores[0].score == 80
        assert dto.category_scores[0].question_count == 2

    async def test_all_unanswered_questions_backfilled(self) -> None:
        """全未回答边界：answers 表为空，3 题全部补齐为 score=0/未作答。"""
        questions_json = json.dumps(
            [
                {
                    "questionIndex": i,
                    "question": f"Q{i}",
                    "type": "short",
                    "category": "Java",
                    "topicSummary": None,
                    "userAnswer": None,
                    "score": None,
                    "feedback": None,
                    "isFollowUp": False,
                    "parentQuestionIndex": None,
                }
                for i in range(3)
            ],
            ensure_ascii=False,
        )
        orm = _make_session_orm(total_questions=3, questions_json=questions_json)
        service, _ = _make_service(session_orm=orm, answers=[])

        dto = await service.get_evaluation("sess123")

        assert len(dto.question_details) == 3
        for d in dto.question_details:
            assert d.user_answer is None
            assert d.score == 0
            assert d.feedback == "该题未作答。"
        # 全未回答时分类得分为空
        assert dto.category_scores == []

    async def test_falls_back_to_answers_only_when_questions_json_invalid(self) -> None:
        """questions_json 解析失败时回退 answers-only 模式，不丢失已答题数据。"""
        orm = _make_session_orm(questions_json="not-valid-json")
        answers = [_make_answer_orm(0, 90), _make_answer_orm(1, 70)]
        service, _ = _make_service(session_orm=orm, answers=answers)

        dto = await service.get_evaluation("sess123")

        # fallback：从 answers 构建，不补齐也不丢失
        assert len(dto.question_details) == 2
        assert dto.question_details[0].score == 90
        assert dto.question_details[1].score == 70

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


class TestGetDetail:
    """#25 面试详情：返回 InterviewDetail（含逐题 answers[]），不限 EVALUATED 状态。"""

    async def test_returns_detail_with_flat_answers(self) -> None:
        created = datetime(2026, 7, 20, 9, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 7, 20, 9, 30, 0, tzinfo=UTC)
        orm = _make_session_orm(created_at=created, completed_at=completed, evaluate_status="COMPLETED")
        answers = [_make_answer_orm(0, 90), _make_answer_orm(1, 70)]
        service, _ = _make_service(session_orm=orm, answers=answers)

        dto = await service.get_detail("sess123")

        assert dto.id == 1
        assert dto.session_id == "sess123"
        assert dto.total_questions == 2
        assert dto.status == "EVALUATED"
        assert dto.evaluate_status == "COMPLETED"
        assert dto.overall_score == 80
        assert dto.overall_feedback == "整体良好"
        assert dto.strengths == ["基础扎实"]
        assert dto.improvements == ["需补深度"]
        # 逐题 answers[]，含 answeredAt + 按 index 合并的参考答案
        assert len(dto.answers) == 2
        a0 = dto.answers[0]
        assert a0.question_index == 0
        assert a0.score == 90
        assert a0.answered_at is not None
        assert a0.reference_answer == "参考1"
        assert a0.key_points == ["要点1"]
        a1 = dto.answers[1]
        assert a1.question_index == 1
        assert a1.reference_answer is None
        assert not a1.key_points

    async def test_works_for_non_evaluated_status(self) -> None:
        """非 EVALUATED 也应返回详情（不抛 INTERVIEW_EVALUATION_NOT_FOUND）。"""
        created = datetime(2026, 7, 20, 9, 0, 0, tzinfo=UTC)
        orm = _make_session_orm(status=SessionStatus.COMPLETED.value, created_at=created)
        answers = [_make_answer_orm(0, 90)]
        service, _ = _make_service(session_orm=orm, answers=answers)

        dto = await service.get_detail("sess123")

        assert dto.status == "COMPLETED"
        assert len(dto.answers) == 2  # questions_json 有 2 题，未答题补齐

    async def test_raises_not_found_when_session_missing(self) -> None:
        service, _ = _make_service(session_orm=None)
        with pytest.raises(BusinessException) as exc:
            await service.get_detail("missing")
        assert exc.value.error_code == ErrorCode.INTERVIEW_SESSION_NOT_FOUND
