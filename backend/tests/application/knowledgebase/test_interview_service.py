"""KnowledgeBaseInterviewService 单元测试（mock 仓储 + 会话服务，组卷算法由 domain 单测覆盖）。"""

import json
import random
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.knowledgebase.interview_service import KnowledgeBaseInterviewService, _normalize_difficulty
from app.application.knowledgebase.question_schemas import CreateKnowledgeBaseInterviewRequest
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase, KnowledgeBaseQuestion


class TestNormalizeDifficulty:
    """_normalize_difficulty 白名单校验（issue #71）。"""

    @pytest.mark.parametrize("value", ["junior", "mid", "senior"])
    def test_valid_values_returned_as_is(self, value: str) -> None:
        assert _normalize_difficulty(value) == value

    def test_trims_whitespace(self) -> None:
        assert _normalize_difficulty("  junior  ") == "junior"

    @pytest.mark.parametrize("value", ["easy", "中级", "hard", "SENIOR"])
    def test_non_standard_values_fallback_to_mid(self, value: str) -> None:
        assert _normalize_difficulty(value) == "mid"

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_blank_values_fallback_to_mid(self, value: str | None) -> None:
        assert _normalize_difficulty(value) == "mid"


def _make_kb(**overrides: Any) -> KnowledgeBase:
    defaults: dict[str, Any] = {
        "id": 1,
        "name": "知识库A",
    }
    defaults.update(overrides)
    return KnowledgeBase(**defaults)


def _make_question(question_id: int = 11, **overrides: Any) -> KnowledgeBaseQuestion:
    follow_ups = [
        {"question": " 追问1 ", "referenceAnswer": "追答1", "keyPoints": ["点1"], "scoringRubric": "规则1"},
        {"question": "", "referenceAnswer": "空题干应被清洗"},
        {"question": "追问2"},
    ]
    defaults: dict[str, Any] = {
        "id": question_id,
        "knowledge_base_id": 1,
        "skill_id": "knowledge-base",
        "difficulty": "mid",
        "type": "REDIS",
        "category": "Redis",
        "question": "什么是缓存穿透？",
        "topic_summary": "缓存穿透",
        "reference_answer": "参考答案",
        "key_points_json": json.dumps(["要点A"], ensure_ascii=False),
        "scoring_rubric": "10分制",
        "follow_ups_json": json.dumps(follow_ups, ensure_ascii=False),
        "source_context": "原文",
        "status": "ACTIVE",
    }
    defaults.update(overrides)
    return KnowledgeBaseQuestion(**defaults)


def _make_service(**mocks: Any) -> tuple[KnowledgeBaseInterviewService, dict[str, Any]]:
    session = MagicMock()
    kb_repository = MagicMock()
    kb_repository.get_by_id = AsyncMock(return_value=mocks.get("kb"))
    question_repository = MagicMock()
    question_repository.find_active_questions = AsyncMock(return_value=mocks.get("questions", []))
    session_service = MagicMock()
    session_service.create_session_from_questions = AsyncMock(return_value=MagicMock())
    service = KnowledgeBaseInterviewService(
        session=session,
        question_repository=question_repository,
        kb_repository=kb_repository,
        interview_session_service=session_service,
        rng=random.Random(42),
    )
    return service, {
        "kb_repository": kb_repository,
        "question_repository": question_repository,
        "session_service": session_service,
    }


def _request(**overrides: Any) -> CreateKnowledgeBaseInterviewRequest:
    defaults: dict[str, Any] = {
        "knowledge_base_id": 1,
        "category": "Redis",
        "difficulty": "mid",
        "main_question_count": 1,
        "follow_up_count": 1,
        "llm_provider": None,
    }
    defaults.update(overrides)
    return CreateKnowledgeBaseInterviewRequest(**defaults)


class TestCreateSession:
    async def test_assembles_and_delegates_to_session_service(self) -> None:
        service, mocks = _make_service(kb=_make_kb(), questions=[_make_question()])

        await service.create_session(_request())

        query_args = mocks["question_repository"].find_active_questions.call_args
        assert query_args.kwargs["kb_id"] == 1
        assert query_args.kwargs["difficulty"] == "mid"
        assert query_args.kwargs["category"] == "Redis"
        create_kwargs = mocks["session_service"].create_session_from_questions.call_args.kwargs
        assert create_kwargs["skill_id"] == "knowledge-base"
        assert create_kwargs["difficulty"] == "mid"
        assert create_kwargs["knowledge_base_id"] == 1
        assert create_kwargs["interview_category"] == "Redis"
        questions = create_kwargs["questions"]
        assert len(questions) == 2  # 1 主问题 + 1 追问
        assert questions[0].reference_answer == "参考答案"
        assert questions[1].is_follow_up
        # 空题干追问被清洗，题干 trim（对齐 Java readUsableFollowUps）
        assert questions[1].question in {"追问1", "追问2"}

    async def test_blank_category_treated_as_all(self) -> None:
        service, mocks = _make_service(kb=_make_kb(), questions=[_make_question()])

        await service.create_session(_request(category="  ", follow_up_count=0))

        assert mocks["question_repository"].find_active_questions.call_args.kwargs["category"] is None
        assert mocks["session_service"].create_session_from_questions.call_args.kwargs["interview_category"] is None

    async def test_blank_difficulty_defaults_mid(self) -> None:
        service, mocks = _make_service(kb=_make_kb(), questions=[_make_question()])

        await service.create_session(_request(difficulty=None))

        assert mocks["question_repository"].find_active_questions.call_args.kwargs["difficulty"] == "mid"

    async def test_kb_not_found(self) -> None:
        service, _ = _make_service(kb=None)

        with pytest.raises(BusinessException) as exc:
            await service.create_session(_request(knowledge_base_id=999))

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_NOT_FOUND

    async def test_insufficient_candidates_bubbles_domain_error(self) -> None:
        service, _ = _make_service(kb=_make_kb(), questions=[])

        with pytest.raises(BusinessException) as exc:
            await service.create_session(_request())

        assert exc.value.error_code is ErrorCode.INTERVIEW_QUESTION_INSUFFICIENT


class TestGetCapacity:
    async def test_builds_capacity_response(self) -> None:
        questions = [
            _make_question(11, category="Redis"),
            _make_question(12, category="MySQL", follow_ups_json=None),
        ]
        service, mocks = _make_service(kb=_make_kb(), questions=questions)

        response = await service.get_capacity(1, category="Redis", difficulty=None, main_question_count=1)

        # 容量查询恒为全方向（category 过滤在 domain 内做 scoped）
        assert mocks["question_repository"].find_active_questions.call_args.kwargs["category"] is None
        assert response.knowledge_base_id == 1
        assert response.category == "Redis"
        assert response.difficulty == "mid"
        assert response.main_question_count == 1
        assert {c.category for c in response.categories} == {"Redis", "MySQL"}
        assert len(response.follow_up_options) == 6
        by_count = {o.follow_up_count: o for o in response.follow_up_options}
        assert by_count[0].available_question_count == 1  # 仅 Redis scoped
        assert by_count[2].available_question_count == 1  # 清洗后 2 个可用追问
        assert by_count[3].available_question_count == 0
        assert by_count[3].selectable is False

    async def test_kb_not_found(self) -> None:
        service, _ = _make_service(kb=None)

        with pytest.raises(BusinessException) as exc:
            await service.get_capacity(999, category=None, difficulty=None, main_question_count=1)

        assert exc.value.error_code is ErrorCode.KNOWLEDGE_BASE_NOT_FOUND
