from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_rag_chat_service
from app.api.rate_limit import limiter
from app.application.knowledgebase.schemas import KnowledgeBaseListItemDTO
from app.application.rag.schemas import (
    RagMessageDTO,
    RagSessionDetailDTO,
    RagSessionDTO,
    RagSessionListItemDTO,
)
from app.domain.errors import BusinessException, ErrorCode
from app.main import app

client = TestClient(app)


def _session_dto() -> RagSessionDTO:
    return RagSessionDTO(
        id=1,
        title="会话",
        knowledge_base_ids=[1, 2],
        created_at=datetime(2026, 7, 20, 10, 0, 0),
    )


def _list_item() -> RagSessionListItemDTO:
    return RagSessionListItemDTO(
        id=1,
        title="会话",
        message_count=3,
        knowledge_base_names=["知识库A", "知识库B"],
        updated_at=datetime(2026, 7, 20, 10, 0, 0),
        is_pinned=True,
    )


def _kb_item() -> KnowledgeBaseListItemDTO:
    return KnowledgeBaseListItemDTO(
        id=1,
        name="知识库A",
        category=None,
        original_filename="doc.pdf",
        file_size=100,
        content_type="application/pdf",
        uploaded_at=datetime(2026, 7, 20, 10, 0, 0),
        last_accessed_at=datetime(2026, 7, 20, 10, 0, 0),
        access_count=0,
        question_count=0,
        vector_status="COMPLETED",
        vector_error=None,
        chunk_count=1,
    )


def _detail() -> RagSessionDetailDTO:
    return RagSessionDetailDTO(
        id=1,
        title="会话",
        knowledge_bases=[_kb_item()],
        messages=[RagMessageDTO(id=1, type="user", content="问题", created_at=datetime(2026, 7, 20, 10, 1, 0))],
        created_at=datetime(2026, 7, 20, 10, 0, 0),
        updated_at=datetime(2026, 7, 20, 10, 0, 0),
    )


async def _sse_gen() -> AsyncIterator[str]:
    yield "data: 这是\n\n"
    yield "data: 答案\n\n"


def _mock_service() -> MagicMock:
    service = MagicMock()
    service.create_session = AsyncMock(return_value=_session_dto())
    service.list_sessions = AsyncMock(return_value=[_list_item()])
    service.get_detail = AsyncMock(return_value=_detail())
    service.update_title = AsyncMock()
    service.toggle_pin = AsyncMock()
    service.delete = AsyncMock()
    service.stream_query = MagicMock(side_effect=lambda *a, **k: _sse_gen())
    return service


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def mock_service() -> Iterator[MagicMock]:
    service = _mock_service()
    app.dependency_overrides[get_rag_chat_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_rag_chat_service, None)


class TestCreateSession:
    def test_creates_session(self, mock_service: MagicMock) -> None:
        response = client.post("/api/rag-chat/sessions", json={"knowledgeBaseIds": [1, 2], "title": "会话"})
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["id"] == 1
        assert body["data"]["knowledgeBaseIds"] == [1, 2]
        mock_service.create_session.assert_awaited_once_with([1, 2], "会话")


class TestListSessions:
    def test_returns_bare_array_with_contract_fields(self, mock_service: MagicMock) -> None:
        response = client.get("/api/rag-chat/sessions")
        body = response.json()
        assert body["code"] == 200
        assert isinstance(body["data"], list)
        item = body["data"][0]
        assert item["id"] == 1
        assert item["messageCount"] == 3
        assert item["knowledgeBaseNames"] == ["知识库A", "知识库B"]
        assert item["isPinned"] is True


class TestGetSession:
    def test_returns_detail_with_typed_messages(self, mock_service: MagicMock) -> None:
        response = client.get("/api/rag-chat/sessions/1")
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["knowledgeBases"][0]["id"] == 1
        assert body["data"]["messages"][0]["type"] == "user"

    def test_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_detail.side_effect = BusinessException(ErrorCode.RAG_SESSION_NOT_FOUND)
        response = client.get("/api/rag-chat/sessions/999")
        assert response.json()["code"] == ErrorCode.RAG_SESSION_NOT_FOUND.code


class TestUpdateTitleAndPin:
    def test_update_title(self, mock_service: MagicMock) -> None:
        response = client.put("/api/rag-chat/sessions/1/title", json={"title": "新标题"})
        assert response.json()["code"] == 200
        mock_service.update_title.assert_awaited_once_with(1, "新标题")

    def test_pin_uses_put_and_returns_null(self, mock_service: MagicMock) -> None:
        response = client.put("/api/rag-chat/sessions/1/pin")
        assert response.status_code == 200
        assert response.json()["data"] is None
        mock_service.toggle_pin.assert_awaited_once_with(1)


class TestDelete:
    def test_delete(self, mock_service: MagicMock) -> None:
        response = client.delete("/api/rag-chat/sessions/1")
        assert response.json()["code"] == 200
        mock_service.delete.assert_awaited_once_with(1)


class TestMessagesStream:
    def test_returns_text_event_stream(self, mock_service: MagicMock) -> None:
        response = client.post("/api/rag-chat/sessions/1/messages/stream", json={"question": "什么是索引？"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "data:" in response.text
        assert "[DONE]" not in response.text
        mock_service.stream_query.assert_called_once_with(1, "什么是索引？")

    def test_rate_limit_blocks_sixth(self, mock_service: MagicMock) -> None:
        results: list[str] = []
        for _ in range(6):
            resp = client.post("/api/rag-chat/sessions/1/messages/stream", json={"question": "q"})
            results.append(resp.text)
        assert all("data:" in r for r in results[:5])
        assert str(ErrorCode.RATE_LIMIT_EXCEEDED.code) in results[5]
