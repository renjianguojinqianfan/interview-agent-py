from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_rag_chat_service
from app.api.rate_limit import limiter
from app.application.rag.schemas import (
    RagAnswerDTO,
    RagMessageDTO,
    RagSessionDetailDTO,
    RagSessionInfoDTO,
    RagSessionPageDTO,
    RagSourceDTO,
)
from app.domain.errors import BusinessException, ErrorCode
from app.main import app

client = TestClient(app)


def _info(session_id: str = "sess-abc") -> RagSessionInfoDTO:
    return RagSessionInfoDTO(
        id=1,
        session_id=session_id,
        title="会话",
        status="ACTIVE",
        pinned=False,
        knowledge_base_ids=[1, 2],
        created_at=datetime(2026, 7, 20, 10, 0, 0),
        updated_at=datetime(2026, 7, 20, 10, 0, 0),
    )


def _detail() -> RagSessionDetailDTO:
    return RagSessionDetailDTO(
        id=1,
        session_id="sess-abc",
        title="会话",
        status="ACTIVE",
        pinned=False,
        knowledge_base_ids=[1, 2],
        created_at=datetime(2026, 7, 20, 10, 0, 0),
        updated_at=datetime(2026, 7, 20, 10, 0, 0),
        messages=[
            RagMessageDTO(id=1, role="user", content="问题", sources=[], created_at=datetime(2026, 7, 20, 10, 1, 0)),
        ],
    )


def _answer() -> RagAnswerDTO:
    return RagAnswerDTO(
        answer="这是答案",
        sources=[RagSourceDTO(content="片段A", score=0.9, kb_id=1)],
        no_result=False,
    )


async def _sse_gen() -> AsyncIterator[str]:
    yield 'data: {"delta": "这是"}\n\n'
    yield 'data: {"delta": "答案"}\n\n'
    yield "data: [DONE]\n\n"


def _mock_service() -> MagicMock:
    service = MagicMock()
    service.create_session = AsyncMock(return_value=_info())
    service.list_sessions = AsyncMock(return_value=RagSessionPageDTO(items=[_info()], total=1, page=1, size=10))
    service.get_detail = AsyncMock(return_value=_detail())
    service.delete = AsyncMock()
    service.toggle_pin = AsyncMock(return_value=True)
    service.get_messages = AsyncMock(return_value=_detail().messages)
    service.query = AsyncMock(return_value=_answer())
    service.ensure_session_exists = AsyncMock()
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
        response = client.post("/api/rag/sessions", json={"knowledgeBaseIds": [1, 2], "title": "会话"})
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["knowledgeBaseIds"] == [1, 2]
        mock_service.create_session.assert_awaited_once_with([1, 2], "会话")


class TestListSessions:
    def test_returns_page(self, mock_service: MagicMock) -> None:
        response = client.get("/api/rag/sessions?page=1&size=10")
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["sessionId"] == "sess-abc"


class TestGetSession:
    def test_returns_detail(self, mock_service: MagicMock) -> None:
        response = client.get("/api/rag/sessions/sess-abc")
        body = response.json()
        assert body["data"]["messages"][0]["role"] == "user"

    def test_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_detail.side_effect = BusinessException(ErrorCode.RAG_SESSION_NOT_FOUND)
        response = client.get("/api/rag/sessions/missing")
        assert response.json()["code"] == ErrorCode.RAG_SESSION_NOT_FOUND.code


class TestDeletePin:
    def test_delete(self, mock_service: MagicMock) -> None:
        response = client.delete("/api/rag/sessions/sess-abc")
        assert response.json()["code"] == 200
        mock_service.delete.assert_awaited_once_with("sess-abc")

    def test_pin_returns_state(self, mock_service: MagicMock) -> None:
        response = client.post("/api/rag/sessions/sess-abc/pin")
        assert response.json()["data"] is True


class TestMessages:
    def test_returns_messages(self, mock_service: MagicMock) -> None:
        response = client.get("/api/rag/sessions/sess-abc/messages")
        body = response.json()
        assert body["code"] == 200
        assert len(body["data"]) == 1


class TestQuery:
    def test_returns_answer(self, mock_service: MagicMock) -> None:
        response = client.post("/api/rag/sessions/sess-abc/query", json={"question": "什么是索引？"})
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["answer"] == "这是答案"
        assert body["data"]["noResult"] is False

    def test_rate_limit_blocks_eleventh(self, mock_service: MagicMock) -> None:
        codes: list[int] = []
        for _ in range(11):
            resp = client.post("/api/rag/sessions/sess-abc/query", json={"question": "q"})
            codes.append(resp.json()["code"])
        assert codes[:10] == [200] * 10
        assert codes[10] == ErrorCode.RATE_LIMIT_EXCEEDED.code


class TestQueryStream:
    def test_returns_event_stream(self, mock_service: MagicMock) -> None:
        response = client.post("/api/rag/sessions/sess-abc/query/stream", json={"question": "什么是索引？"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "data:" in response.text
        assert "[DONE]" in response.text
        mock_service.ensure_session_exists.assert_awaited_once_with("sess-abc")

    def test_rate_limit_blocks_sixth(self, mock_service: MagicMock) -> None:
        results: list[str] = []
        for _ in range(6):
            resp = client.post("/api/rag/sessions/sess-abc/query/stream", json={"question": "q"})
            results.append(resp.text)
        assert all("data:" in r for r in results[:5])
        assert str(ErrorCode.RATE_LIMIT_EXCEEDED.code) in results[5]
