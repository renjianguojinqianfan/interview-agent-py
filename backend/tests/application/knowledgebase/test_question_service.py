"""KnowledgeBaseQuestionService 单元测试（mock 仓储，镜像 test_service.py 风格）。"""

import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.knowledgebase.question_schemas import (
    CreateKnowledgeBaseQuestionRequest,
    GenerateKnowledgeBaseQuestionsRequest,
    KnowledgeBaseQuestionFollowUpDTO,
    QuestionGenerationConfigDTO,
    QuestionGenStatusResponse,
    UpdateKnowledgeBaseQuestionRequest,
)
from app.application.knowledgebase.question_service import KnowledgeBaseQuestionService
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase, KnowledgeBaseQuestion


def _make_kb(**overrides: Any) -> KnowledgeBase:
    defaults: dict[str, Any] = {
        "id": 1,
        "file_hash": "hash123",
        "original_filename": "doc.pdf",
        "name": "知识库A",
    }
    defaults.update(overrides)
    return KnowledgeBase(**defaults)


def _make_question(**overrides: Any) -> KnowledgeBaseQuestion:
    defaults: dict[str, Any] = {
        "id": 11,
        "knowledge_base_id": 1,
        "skill_id": "knowledge-base",
        "difficulty": "mid",
        "type": "CONCEPT",
        "category": "Redis",
        "question": "什么是缓存穿透？",
        "topic_summary": "缓存三大问题",
        "reference_answer": "查询不存在的数据……",
        "key_points_json": json.dumps(["布隆过滤器", "空值缓存"], ensure_ascii=False),
        "scoring_rubric": "说出两种方案得满分",
        "follow_ups_json": json.dumps(
            [{"question": "如何选型？", "referenceAnswer": "看误判率", "keyPoints": ["误判率"], "scoringRubric": None}],
            ensure_ascii=False,
        ),
        "source_context": "第 3 章",
        "kb_content_hash": "hash123",
        "status": "ACTIVE",
        "created_at": datetime(2026, 7, 25, 10, 0, 0),
        "updated_at": datetime(2026, 7, 25, 11, 0, 0),
    }
    defaults.update(overrides)
    return KnowledgeBaseQuestion(**defaults)


def _make_service(**mocks: Any) -> tuple[KnowledgeBaseQuestionService, dict[str, Any]]:
    session = AsyncMock()

    question_repository = MagicMock()
    question_repository.list_by_knowledge_base = AsyncMock(return_value=mocks.get("questions", []))
    question_repository.category_counts = AsyncMock(return_value=mocks.get("category_counts", []))
    question_repository.get_by_id = AsyncMock(return_value=mocks.get("question"))
    question_repository.delete = AsyncMock()

    async def _save(_session: Any, question: KnowledgeBaseQuestion) -> KnowledgeBaseQuestion:
        if question.id is None:
            question.id = 11
        return question

    question_repository.save = AsyncMock(side_effect=_save)

    kb_repository = MagicMock()
    kb_repository.get_by_id = AsyncMock(return_value=mocks.get("kb"))

    state_service = MagicMock()
    state_service.create_task = AsyncMock(return_value=mocks.get("task_response"))
    state_service.get_status = AsyncMock(return_value=mocks.get("status_response"))

    producer = MagicMock()
    producer.send_task = AsyncMock(return_value="100-0")

    service = KnowledgeBaseQuestionService(
        session=session,
        question_repository=question_repository,
        kb_repository=kb_repository,
        state_service=state_service,
        producer=producer,
    )
    return service, {
        "session": session,
        "question_repository": question_repository,
        "kb_repository": kb_repository,
        "state_service": state_service,
        "producer": producer,
    }


class TestListQuestions:
    async def test_maps_entity_to_dto_with_json_fields(self) -> None:
        service, _ = _make_service(questions=[_make_question()], kb=_make_kb())

        result = await service.list_questions(1, None, None, None, None)

        assert len(result) == 1
        dto = result[0]
        assert dto.id == 11
        assert dto.knowledge_base_id == 1
        assert dto.knowledge_base_name == "知识库A"
        assert dto.skill_id == "knowledge-base"
        assert dto.key_points == ["布隆过滤器", "空值缓存"]
        assert dto.follow_ups[0].question == "如何选型？"
        assert dto.follow_ups[0].reference_answer == "看误判率"
        assert dto.status == "ACTIVE"

    async def test_passes_status_filter_to_repository(self) -> None:
        service, mocks = _make_service(questions=[], kb=_make_kb())

        await service.list_questions(1, "DRAFT", None, None, None)

        mocks["question_repository"].list_by_knowledge_base.assert_awaited_once_with(
            mocks["session"], 1, status="DRAFT"
        )

    async def test_filters_category_and_difficulty_in_memory(self) -> None:
        questions = [
            _make_question(id=1, category="Redis", difficulty="mid"),
            _make_question(id=2, category="MySQL", difficulty="mid"),
            _make_question(id=3, category="Redis", difficulty="senior"),
        ]
        service, _ = _make_service(questions=questions, kb=_make_kb())

        result = await service.list_questions(1, None, " Redis ", "mid", None)

        assert [dto.id for dto in result] == [1]

    async def test_keyword_matches_case_insensitive_across_fields(self) -> None:
        questions = [
            _make_question(id=1, question="What is CAP theorem?"),
            _make_question(id=2, reference_answer="讲清楚 Cap 定理即可"),
            _make_question(id=3, question="无关", reference_answer=None, scoring_rubric=None, topic_summary=None),
        ]
        service, _ = _make_service(questions=questions, kb=_make_kb())

        result = await service.list_questions(1, None, None, None, "cap")

        assert [dto.id for dto in result] == [1, 2]

    async def test_invalid_json_fields_fallback_to_empty_lists(self) -> None:
        service, _ = _make_service(
            questions=[_make_question(key_points_json="not-json", follow_ups_json=None)],
            kb=_make_kb(),
        )

        result = await service.list_questions(1, None, None, None, None)

        assert result[0].key_points == []
        assert result[0].follow_ups == []

    async def test_missing_kb_yields_none_name(self) -> None:
        service, _ = _make_service(questions=[_make_question()], kb=None)

        result = await service.list_questions(1, None, None, None, None)

        assert result[0].knowledge_base_name is None


class TestListCategories:
    async def test_maps_counts_to_dtos(self) -> None:
        service, _ = _make_service(category_counts=[("Redis", 5), ("MySQL", 2)])

        result = await service.list_categories(1)

        assert [(c.category, c.count) for c in result] == [("Redis", 5), ("MySQL", 2)]


def _create_request(**overrides: Any) -> CreateKnowledgeBaseQuestionRequest:
    defaults: dict[str, Any] = {"category": "Redis", "question": "什么是缓存穿透？"}
    defaults.update(overrides)
    return CreateKnowledgeBaseQuestionRequest(**defaults)


class TestCreateQuestion:
    async def test_defaults_and_kb_hash_snapshot(self) -> None:
        service, mocks = _make_service(kb=_make_kb())

        dto = await service.create_question(1, _create_request())

        saved: KnowledgeBaseQuestion = mocks["question_repository"].save.await_args.args[1]
        assert saved.skill_id == "knowledge-base"
        assert saved.difficulty == "mid"
        assert saved.status == "DRAFT"
        assert saved.kb_content_hash == "hash123"
        assert saved.key_points_json == "[]"
        assert saved.follow_ups_json == "[]"
        assert dto.category == "Redis"
        mocks["session"].commit.assert_awaited_once()

    async def test_trims_and_serializes_fields(self) -> None:
        service, mocks = _make_service(kb=_make_kb())
        request = _create_request(
            difficulty=" senior ",
            category=" Redis ",
            question="  题干  ",
            topic_summary="   ",
            key_points=[" 要点A ", "  "],
            follow_ups=[
                KnowledgeBaseQuestionFollowUpDTO(question=" 追问1 ", key_points=[" p1 ", " "]),
                KnowledgeBaseQuestionFollowUpDTO(question="   "),
            ],
            status="ACTIVE",
        )

        dto = await service.create_question(1, request)

        saved: KnowledgeBaseQuestion = mocks["question_repository"].save.await_args.args[1]
        assert saved.difficulty == "senior"
        assert saved.category == "Redis"
        assert saved.question == "题干"
        assert saved.topic_summary is None
        assert json.loads(saved.key_points_json) == ["要点A"]
        follow_ups = json.loads(saved.follow_ups_json)
        assert len(follow_ups) == 1  # 空题干追问被丢弃
        assert follow_ups[0]["question"] == "追问1"
        assert follow_ups[0]["keyPoints"] == ["p1"]
        assert saved.status == "ACTIVE"
        assert dto.status == "ACTIVE"

    async def test_blank_category_or_question_rejected(self) -> None:
        service, _ = _make_service(kb=_make_kb())

        with pytest.raises(BusinessException) as exc1:
            await service.create_question(1, _create_request(category="   "))
        assert exc1.value.error_code == ErrorCode.BAD_REQUEST

        with pytest.raises(BusinessException) as exc2:
            await service.create_question(1, _create_request(question="   "))
        assert exc2.value.error_code == ErrorCode.BAD_REQUEST

    async def test_kb_not_found(self) -> None:
        service, _ = _make_service(kb=None)

        with pytest.raises(BusinessException) as exc:
            await service.create_question(999, _create_request())
        assert exc.value.error_code == ErrorCode.KNOWLEDGE_BASE_NOT_FOUND


class TestUpdateQuestion:
    async def test_partial_update_skips_none_fields(self) -> None:
        question = _make_question()
        service, mocks = _make_service(question=question, kb=_make_kb())

        dto = await service.update_question(
            11, UpdateKnowledgeBaseQuestionRequest(reference_answer=" 新答案 ", status="DRAFT")
        )

        assert question.reference_answer == "新答案"
        assert question.status == "DRAFT"
        assert question.question == "什么是缓存穿透？"  # 未提供字段不变
        assert question.category == "Redis"
        assert dto.reference_answer == "新答案"
        mocks["session"].commit.assert_awaited_once()

    async def test_explicit_blank_reference_answer_clears_field(self) -> None:
        question = _make_question()
        service, _ = _make_service(question=question, kb=_make_kb())

        await service.update_question(11, UpdateKnowledgeBaseQuestionRequest(reference_answer="   "))

        assert question.reference_answer is None

    async def test_blank_category_or_question_rejected(self) -> None:
        service, _ = _make_service(question=_make_question(), kb=_make_kb())

        with pytest.raises(BusinessException) as exc1:
            await service.update_question(11, UpdateKnowledgeBaseQuestionRequest(category="   "))
        assert exc1.value.error_code == ErrorCode.BAD_REQUEST

        with pytest.raises(BusinessException) as exc2:
            await service.update_question(11, UpdateKnowledgeBaseQuestionRequest(question="   "))
        assert exc2.value.error_code == ErrorCode.BAD_REQUEST

    async def test_question_not_found(self) -> None:
        service, _ = _make_service(question=None)

        with pytest.raises(BusinessException) as exc:
            await service.update_question(999, UpdateKnowledgeBaseQuestionRequest())
        assert exc.value.error_code == ErrorCode.INTERVIEW_QUESTION_NOT_FOUND


class TestUpdateStatus:
    async def test_switches_status(self) -> None:
        question = _make_question(status="DRAFT")
        service, mocks = _make_service(question=question, kb=_make_kb())

        dto = await service.update_status(11, "ACTIVE")

        assert question.status == "ACTIVE"
        assert dto.status == "ACTIVE"
        mocks["session"].commit.assert_awaited_once()

    async def test_question_not_found(self) -> None:
        service, _ = _make_service(question=None)

        with pytest.raises(BusinessException) as exc:
            await service.update_status(999, "ACTIVE")
        assert exc.value.error_code == ErrorCode.INTERVIEW_QUESTION_NOT_FOUND


class TestDeleteQuestion:
    async def test_deletes_existing(self) -> None:
        question = _make_question()
        service, mocks = _make_service(question=question)

        await service.delete_question(11)

        mocks["question_repository"].delete.assert_awaited_once_with(mocks["session"], question)
        mocks["session"].commit.assert_awaited_once()

    async def test_question_not_found(self) -> None:
        service, _ = _make_service(question=None)

        with pytest.raises(BusinessException) as exc:
            await service.delete_question(999)
        assert exc.value.error_code == ErrorCode.INTERVIEW_QUESTION_NOT_FOUND


def _task_response(**overrides: Any) -> QuestionGenStatusResponse:
    defaults: dict[str, Any] = {
        "knowledge_base_id": 1,
        "question_gen_status": "QUEUED",
        "question_gen_task_id": "task-1",
    }
    defaults.update(overrides)
    return QuestionGenStatusResponse(**defaults)


class TestSubmitGenerationTask:
    async def test_normalizes_config_defaults(self) -> None:
        service, mocks = _make_service(task_response=_task_response())

        await service.submit_generation_task(
            1, GenerateKnowledgeBaseQuestionsRequest(question_count=10, category_limit=3)
        )

        config: QuestionGenerationConfigDTO = mocks["state_service"].create_task.await_args.args[1]
        assert config.difficulty == "mid"  # 缺省难度
        assert config.follow_up_count == 2  # 缺省追问数
        assert config.category_limit == 3
        assert config.llm_provider is None

    async def test_sends_task_with_created_task_id(self) -> None:
        service, mocks = _make_service(task_response=_task_response(question_gen_task_id="task-9"))

        response = await service.submit_generation_task(
            1, GenerateKnowledgeBaseQuestionsRequest(question_count=5, category_limit=2)
        )

        payload = mocks["producer"].send_task.await_args.args[0]
        assert payload.kb_id == 1
        assert payload.task_id == "task-9"
        assert response.question_gen_task_id == "task-9"

    async def test_send_failure_returns_fresh_status(self) -> None:
        service, mocks = _make_service(
            task_response=_task_response(),
            status_response=_task_response(question_gen_status="FAILED"),
        )
        mocks["producer"].send_task.return_value = ""  # 入队失败（base producer 返回空 id）

        response = await service.submit_generation_task(
            1, GenerateKnowledgeBaseQuestionsRequest(question_count=5, category_limit=2)
        )

        assert response.question_gen_status == "FAILED"

    async def test_get_generation_status_delegates(self) -> None:
        service, mocks = _make_service(status_response=_task_response(question_gen_status="PROCESSING"))

        response = await service.get_generation_status(1)

        assert response.question_gen_status == "PROCESSING"
        mocks["state_service"].get_status.assert_awaited_once_with(1)
