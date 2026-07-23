"""语音评估读侧服务单元测试：mock 仓储，验证 DB->DTO 重建与契约对齐（#24）。"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.application.voice.service import VoiceEvaluationService, VoiceSessionService
from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewEvaluation as VoiceInterviewEvaluationORM,
)
from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewSession as VoiceInterviewSessionORM,
)


def _make_session_orm(**overrides: object) -> VoiceInterviewSessionORM:
    defaults: dict[str, object] = {
        "id": 7,
        "user_id": "default",
        "role_type": "Java面试官",
        "skill_id": "java-backend",
        "difficulty": "mid",
        "current_phase": "COMPLETED",
        "status": "COMPLETED",
        "planned_duration": 30,
        "evaluate_status": AsyncTaskStatus.COMPLETED.value,
        "evaluate_error": None,
    }
    defaults.update(overrides)
    return VoiceInterviewSessionORM(**defaults)  # type: ignore[arg-type]


def _make_evaluation_orm(**overrides: object) -> VoiceInterviewEvaluationORM:
    defaults: dict[str, object] = {
        "id": 1,
        "session_id": 7,
        "overall_score": 85,
        "overall_feedback": "整体表现良好",
        "question_evaluations_json": json.dumps(
            [
                {
                    "questionIndex": 0,
                    "question": "Q0",
                    "category": "Java",
                    "userAnswer": "A0",
                    "score": 90,
                    "feedback": "好",
                },
                {
                    "questionIndex": 1,
                    "question": "Q1",
                    "category": "MySQL",
                    "userAnswer": "A1",
                    "score": 70,
                    "feedback": "一般",
                },
            ],
            ensure_ascii=False,
        ),
        "strengths_json": json.dumps(["基础扎实"], ensure_ascii=False),
        "improvements_json": json.dumps(["需加强系统设计"], ensure_ascii=False),
        "reference_answers_json": json.dumps(
            [{"questionIndex": 0, "question": "Q0", "referenceAnswer": "参考0", "keyPoints": ["要点0"]}],
            ensure_ascii=False,
        ),
    }
    defaults.update(overrides)
    return VoiceInterviewEvaluationORM(**defaults)  # type: ignore[arg-type]


def _make_service(
    session_orm: VoiceInterviewSessionORM | None,
    evaluation_orm: VoiceInterviewEvaluationORM | None = None,
) -> VoiceEvaluationService:
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=session_orm)
    repository.get_evaluation_by_session = AsyncMock(return_value=evaluation_orm)
    return VoiceEvaluationService(session=MagicMock(), repository=repository)


class TestGetEvaluationContract:
    async def test_completed_returns_flat_answers_with_reference(self) -> None:
        """完成态：返回扁平 answers[]（含 referenceAnswer/keyPoints）+ sessionId + totalQuestions。"""
        service = _make_service(_make_session_orm(), _make_evaluation_orm())

        dto = await service.get_evaluation(7)

        assert dto.evaluate_status == "COMPLETED"
        assert dto.evaluate_error is None
        assert dto.evaluation is not None
        detail = dto.evaluation
        assert detail.session_id == 7
        assert detail.total_questions == 2
        assert detail.overall_score == 85
        assert detail.overall_feedback == "整体表现良好"
        assert detail.strengths == ["基础扎实"]
        assert detail.improvements == ["需加强系统设计"]
        # 扁平 answers[]，按 questionIndex 合并逐题明细 + 参考答案
        assert len(detail.answers) == 2
        a0 = detail.answers[0]
        assert a0.question_index == 0
        assert a0.question == "Q0"
        assert a0.category == "Java"
        assert a0.user_answer == "A0"
        assert a0.score == 90
        assert a0.feedback == "好"
        assert a0.reference_answer == "参考0"
        assert a0.key_points == ["要点0"]
        # 无参考答案的题：referenceAnswer/keyPoints 为空
        a1 = detail.answers[1]
        assert a1.question_index == 1
        assert a1.reference_answer is None
        assert not a1.key_points

    async def test_failed_status_exposes_evaluate_error(self) -> None:
        """FAILED 态：evaluateError 非空，evaluation 为 None。"""
        session = _make_session_orm(evaluate_status=AsyncTaskStatus.FAILED.value, evaluate_error="评估超时")
        service = _make_service(session, None)

        dto = await service.get_evaluation(7)

        assert dto.evaluate_status == "FAILED"
        assert dto.evaluate_error == "评估超时"
        assert dto.evaluation is None


class TestListSessionsContract:
    """#27 会话列表元数据对齐：createdAt/actualDuration/messageCount/evaluateError。"""

    async def test_metas_include_created_at_and_message_count(self) -> None:
        now = datetime(2026, 7, 21, 10, 0, 0, tzinfo=UTC)
        row = _make_session_orm(
            id=5,
            status="COMPLETED",
            actual_duration=120,
            evaluate_status="COMPLETED",
            evaluate_error=None,
            start_time=now,
            created_at=now,
            updated_at=now,
        )
        repository = MagicMock()
        repository.list_by_user = AsyncMock(return_value=[row])
        repository.count_messages_by_sessions = AsyncMock(return_value={5: 4})
        service = VoiceSessionService(
            session=MagicMock(),
            repository=repository,
            session_cache=MagicMock(),
            evaluate_producer=MagicMock(),
        )

        metas = await service.list_sessions()

        assert len(metas) == 1
        m = metas[0]
        assert m.session_id == 5
        assert m.created_at is not None
        assert m.actual_duration == 120
        assert m.message_count == 4
        # 一次聚合查询拿到所有会话的消息数（避 N+1）
        repository.count_messages_by_sessions.assert_awaited_once_with(service._session, [5])
