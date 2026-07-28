"""QuestionGenerationService 单元测试（mock 检索/LLM/状态服务，行为对齐 Java executeGeneration）。"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.knowledgebase.generation_service import (
    GeneratedQuestion,
    GeneratedQuestionList,
    QuestionGenerationService,
)
from app.application.knowledgebase.question_schemas import (
    KnowledgeBaseQuestionFollowUpDTO,
    QuestionGenerationConfigDTO,
)
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase, KnowledgeBaseQuestion
from app.infrastructure.vector.repository import SearchResult


def _make_kb(**overrides: Any) -> KnowledgeBase:
    defaults: dict[str, Any] = {
        "id": 1,
        "name": "知识库A",
        "question_gen_task_id": "task-1",
    }
    defaults.update(overrides)
    return KnowledgeBase(**defaults)


def _config(**overrides: Any) -> QuestionGenerationConfigDTO:
    defaults: dict[str, Any] = {
        "difficulty": "mid",
        "question_count": 5,
        "follow_up_count": 2,
        "category_limit": 3,
        "llm_provider": None,
    }
    defaults.update(overrides)
    return QuestionGenerationConfigDTO(**defaults)


def _generated(question: str, **overrides: Any) -> GeneratedQuestion:
    defaults: dict[str, Any] = {
        "category": "Redis",
        "type": "REDIS",
        "question": question,
        "topicSummary": "摘要",
        "referenceAnswer": "参考答案",
        "keyPoints": ["要点"],
        "scoringRubric": "规则",
        "followUps": [],
    }
    defaults.update(overrides)
    return GeneratedQuestion(**defaults)


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.session = AsyncMock()

    def __call__(self) -> Any:
        factory = self

        class _Ctx:
            async def __aenter__(self) -> Any:
                return factory.session

            async def __aexit__(self, *args: Any) -> None:
                return None

        return _Ctx()


def _search_result(content: str) -> SearchResult:
    return SearchResult(content=content, score=0.9, kb_id=1)


def _make_service(
    kb: KnowledgeBase | None = None,
    search_results: list[SearchResult] | None = None,
    llm_output: GeneratedQuestionList | None = None,
    first_doc_hash: str | None = "hash123",
) -> tuple[QuestionGenerationService, dict[str, Any]]:
    session_factory = _FakeSessionFactory()

    kb_repository = MagicMock()
    kb_repository.get_by_id = AsyncMock(return_value=kb)

    question_repository = MagicMock()
    question_repository.category_counts = AsyncMock(return_value=[])
    question_repository.find_recent_questions = AsyncMock(return_value=[])

    vector_repository = MagicMock()
    vector_repository.search = AsyncMock(return_value=search_results or [])

    embeddings = MagicMock()
    embeddings.aembed_query = AsyncMock(return_value=[0.1, 0.2])

    llm_registry = MagicMock()
    llm_registry.get_default_embeddings = AsyncMock(return_value=embeddings)
    llm_registry.resolve_provider_id_by_name = AsyncMock(return_value=None)
    llm_registry.get_plain_chat_client = AsyncMock(return_value=MagicMock())

    invoker = MagicMock()
    invoker.invoke = AsyncMock(return_value=llm_output or GeneratedQuestionList(questions=[]))

    state_service = MagicMock()
    state_service.replace_questions_and_complete = AsyncMock(return_value=True)

    document_repository = MagicMock()
    document_repository.find_first_hash_by_kb = AsyncMock(return_value=first_doc_hash)

    service = QuestionGenerationService(
        session_factory=session_factory,  # type: ignore[arg-type]
        kb_repository=kb_repository,
        question_repository=question_repository,
        vector_repository=vector_repository,
        llm_registry=llm_registry,
        invoker=invoker,
        state_service=state_service,
        document_repository=document_repository,
    )
    return service, {
        "vector_repository": vector_repository,
        "invoker": invoker,
        "state_service": state_service,
        "llm_registry": llm_registry,
        "document_repository": document_repository,
    }


class TestTaskIdGuard:
    async def test_stale_task_id_aborts_without_llm(self) -> None:
        service, mocks = _make_service(kb=_make_kb(question_gen_task_id="task-new"))

        await service.execute_generation(1, "task-old", _config())

        mocks["invoker"].invoke.assert_not_awaited()
        mocks["state_service"].replace_questions_and_complete.assert_not_awaited()

    async def test_kb_not_found_raises(self) -> None:
        service, _ = _make_service(kb=None)

        with pytest.raises(BusinessException) as exc:
            await service.execute_generation(999, "task-1", _config())
        assert exc.value.error_code == ErrorCode.KNOWLEDGE_BASE_NOT_FOUND


class TestContextRetrieval:
    async def test_empty_retrieval_raises_query_failed(self) -> None:
        service, _ = _make_service(kb=_make_kb(), search_results=[])

        with pytest.raises(BusinessException) as exc:
            await service.execute_generation(1, "task-1", _config())
        assert exc.value.error_code == ErrorCode.KNOWLEDGE_BASE_QUERY_FAILED

    async def test_deduplicates_chunks_across_queries(self) -> None:
        service, mocks = _make_service(
            kb=_make_kb(),
            search_results=[_search_result("片段A"), _search_result("片段A"), _search_result("片段B")],
            llm_output=GeneratedQuestionList(questions=[_generated("题1")]),
        )

        await service.execute_generation(1, "task-1", _config())

        # 4 组查询词各检索一次
        assert mocks["vector_repository"].search.await_count == 4
        user_prompt = mocks["invoker"].invoke.await_args.kwargs["user_prompt"]
        assert user_prompt.count("片段A") == 1

    async def test_context_truncated_to_max_chars(self) -> None:
        service, mocks = _make_service(
            kb=_make_kb(),
            search_results=[_search_result("长" * 6000)],
            llm_output=GeneratedQuestionList(questions=[_generated("题1")]),
        )

        await service.execute_generation(1, "task-1", _config())

        user_prompt = mocks["invoker"].invoke.await_args.kwargs["user_prompt"]
        assert "已截断" in user_prompt


class TestEntityBuilding:
    async def test_normalized_dedup_counts_skipped(self) -> None:
        output = GeneratedQuestionList(
            questions=[
                _generated("什么是 Redis？"),
                _generated("什么是redis"),  # NFC+小写+仅字母数字后同 key -> 跳过
                _generated("   "),  # 空题干 -> 跳过
                _generated("什么是缓存穿透？"),
            ]
        )
        service, mocks = _make_service(kb=_make_kb(), search_results=[_search_result("片段")], llm_output=output)

        await service.execute_generation(1, "task-1", _config())

        call = mocks["state_service"].replace_questions_and_complete.await_args
        questions: list[KnowledgeBaseQuestion] = call.args[2]
        skipped: int = call.args[3]
        assert [q.question for q in questions] == ["什么是 Redis？", "什么是缓存穿透？"]
        assert skipped == 2

    async def test_entity_fields_and_defaults(self) -> None:
        output = GeneratedQuestionList(
            questions=[
                _generated(
                    "题1",
                    category="",
                    followUps=[
                        KnowledgeBaseQuestionFollowUpDTO(question="追问1"),
                        KnowledgeBaseQuestionFollowUpDTO(question="追问2"),
                        KnowledgeBaseQuestionFollowUpDTO(question="追问3"),
                    ],
                )
            ]
        )
        service, mocks = _make_service(kb=_make_kb(), search_results=[_search_result("片段")], llm_output=output)

        await service.execute_generation(1, "task-1", _config(follow_up_count=2))

        question: KnowledgeBaseQuestion = mocks["state_service"].replace_questions_and_complete.await_args.args[2][0]
        assert question.skill_id == "knowledge-base"
        assert question.difficulty == "mid"
        assert question.category == "知识库A"  # 空 category 回落知识库名
        assert question.status == "DRAFT"
        assert question.kb_content_hash == "hash123"  # 取自首文档 hash
        assert len(json.loads(question.follow_ups_json)) == 2  # 追问截断至 followUpCount
        assert question.source_context  # 记录检索上下文

    async def test_empty_llm_result_raises(self) -> None:
        service, _ = _make_service(
            kb=_make_kb(),
            search_results=[_search_result("片段")],
            llm_output=GeneratedQuestionList(questions=[]),
        )

        with pytest.raises(BusinessException) as exc:
            await service.execute_generation(1, "task-1", _config())
        assert exc.value.error_code == ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED

    async def test_all_blank_questions_raises(self) -> None:
        service, _ = _make_service(
            kb=_make_kb(),
            search_results=[_search_result("片段")],
            llm_output=GeneratedQuestionList(questions=[_generated("  ")]),
        )

        with pytest.raises(BusinessException) as exc:
            await service.execute_generation(1, "task-1", _config())
        assert exc.value.error_code == ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED


class TestKbContentHash:
    async def test_kb_content_hash_uses_first_document_hash(self) -> None:
        output = GeneratedQuestionList(questions=[_generated("题1")])
        service, mocks = _make_service(
            kb=_make_kb(), search_results=[_search_result("片段")], llm_output=output, first_doc_hash="doc-hash-abc"
        )

        await service.execute_generation(1, "task-1", _config())

        mocks["document_repository"].find_first_hash_by_kb.assert_awaited_once()
        question: KnowledgeBaseQuestion = mocks["state_service"].replace_questions_and_complete.await_args.args[2][0]
        assert question.kb_content_hash == "doc-hash-abc"

    async def test_kb_content_hash_none_when_no_documents(self) -> None:
        output = GeneratedQuestionList(questions=[_generated("题1")])
        service, mocks = _make_service(
            kb=_make_kb(), search_results=[_search_result("片段")], llm_output=output, first_doc_hash=None
        )

        await service.execute_generation(1, "task-1", _config())

        question: KnowledgeBaseQuestion = mocks["state_service"].replace_questions_and_complete.await_args.args[2][0]
        assert question.kb_content_hash is None


class TestCompletion:
    async def test_stale_result_discarded_silently(self) -> None:
        service, mocks = _make_service(
            kb=_make_kb(),
            search_results=[_search_result("片段")],
            llm_output=GeneratedQuestionList(questions=[_generated("题1")]),
        )
        mocks["state_service"].replace_questions_and_complete.return_value = False

        await service.execute_generation(1, "task-1", _config())  # 不应抛异常

    async def test_resolves_provider_by_name(self) -> None:
        service, mocks = _make_service(
            kb=_make_kb(),
            search_results=[_search_result("片段")],
            llm_output=GeneratedQuestionList(questions=[_generated("题1")]),
        )
        mocks["llm_registry"].resolve_provider_id_by_name.return_value = 7

        await service.execute_generation(1, "task-1", _config(llm_provider="qwen"))

        mocks["llm_registry"].resolve_provider_id_by_name.assert_awaited_once_with("qwen")
        mocks["llm_registry"].get_plain_chat_client.assert_awaited_once_with(7)
