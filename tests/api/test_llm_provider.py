from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm_provider_service
from app.application.llm_provider.schemas import (
    AsrConfigDTO,
    DefaultProviderDTO,
    ProviderDTO,
    ProviderTestResult,
    TtsConfigDTO,
)
from app.domain.errors import BusinessException, ErrorCode
from app.main import app

client = TestClient(app)


def _provider_dto(
    provider_id: int = 1,
    default_chat: bool = True,
    default_emb: bool = True,
) -> ProviderDTO:
    return ProviderDTO(
        id=provider_id,
        provider_name="dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        masked_api_key="sk-***key",
        model="qwen3.5-flash",
        embedding_model="text-embedding-v3",
        embedding_dimensions=1024,
        supports_embedding=True,
        temperature=0.2,
        default_chat_provider=default_chat,
        default_embedding_provider=default_emb,
    )


def _asr_dto() -> AsrConfigDTO:
    return AsrConfigDTO(
        url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        model="qwen3-asr-flash-realtime",
        masked_api_key="",
        language="zh",
        format="pcm",
        sample_rate=16000,
        enable_turn_detection=True,
        turn_detection_type="server_vad",
        turn_detection_threshold=0.0,
        turn_detection_silence_duration_ms=2000,
    )


def _tts_dto() -> TtsConfigDTO:
    return TtsConfigDTO(
        model="qwen3-tts-flash-realtime",
        masked_api_key="",
        voice="Cherry",
        format="pcm",
        sample_rate=24000,
        mode="commit",
        language_type="Chinese",
        speech_rate=1.0,
        volume=60,
    )


def _override_service(mock_service: AsyncMock) -> None:
    app.dependency_overrides[get_llm_provider_service] = lambda: mock_service


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


class TestListProviders:
    def test_list_providers(self) -> None:
        svc = AsyncMock()
        svc.list_providers = AsyncMock(return_value=[_provider_dto(1), _provider_dto(2, False, False)])
        _override_service(svc)
        resp = client.get("/api/llm-provider/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 200
        assert len(data["data"]) == 2


class TestGetProvider:
    def test_get_provider(self) -> None:
        svc = AsyncMock()
        svc.get_provider = AsyncMock(return_value=_provider_dto(1))
        _override_service(svc)
        resp = client.get("/api/llm-provider/1")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == 1

    def test_get_provider_not_found(self) -> None:
        svc = AsyncMock()
        svc.get_provider = AsyncMock(side_effect=BusinessException(ErrorCode.PROVIDER_NOT_FOUND))
        _override_service(svc)
        resp = client.get("/api/llm-provider/999")
        assert resp.status_code == 200
        assert resp.json()["code"] == 11001


class TestCreateProvider:
    def test_create_provider(self) -> None:
        svc = AsyncMock()
        svc.create_provider = AsyncMock()
        _override_service(svc)
        resp = client.post(
            "/api/llm-provider",
            json={
                "providerName": "openai",
                "baseUrl": "https://api.openai.com/v1",
                "apiKey": "sk-test",
                "model": "gpt-4",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 200
        svc.create_provider.assert_called_once()


class TestUpdateProvider:
    def test_update_provider(self) -> None:
        svc = AsyncMock()
        svc.update_provider = AsyncMock()
        _override_service(svc)
        resp = client.put("/api/llm-provider/1", json={"model": "qwen-max"})
        assert resp.status_code == 200
        svc.update_provider.assert_called_once()


class TestDeleteProvider:
    def test_delete_provider(self) -> None:
        svc = AsyncMock()
        svc.delete_provider = AsyncMock()
        _override_service(svc)
        resp = client.delete("/api/llm-provider/2")
        assert resp.status_code == 200
        svc.delete_provider.assert_called_once()

    def test_delete_default_provider_raises(self) -> None:
        svc = AsyncMock()
        svc.delete_provider = AsyncMock(side_effect=BusinessException(ErrorCode.PROVIDER_DEFAULT_CANNOT_DELETE))
        _override_service(svc)
        resp = client.delete("/api/llm-provider/1")
        assert resp.json()["code"] == 11007


class TestTestProvider:
    def test_test_provider(self) -> None:
        svc = AsyncMock()
        svc.test_provider = AsyncMock(
            return_value=ProviderTestResult(success=True, message="连接成功", model="qwen3.5-flash")
        )
        _override_service(svc)
        resp = client.post("/api/llm-provider/1/test")
        assert resp.status_code == 200
        assert resp.json()["data"]["success"] is True


class TestReloadProviders:
    def test_reload_providers(self) -> None:
        svc = AsyncMock()
        svc.reload_providers = AsyncMock()
        _override_service(svc)
        resp = client.post("/api/llm-provider/reload")
        assert resp.status_code == 200
        svc.reload_providers.assert_called_once()


class TestDefaultProvider:
    def test_get_default_provider(self) -> None:
        svc = AsyncMock()
        svc.get_default_provider = AsyncMock(
            return_value=DefaultProviderDTO(default_provider=1, default_embedding_provider=1)
        )
        _override_service(svc)
        resp = client.get("/api/llm-provider/default-provider")
        assert resp.status_code == 200
        assert resp.json()["data"]["defaultProvider"] == 1

    def test_update_default_provider(self) -> None:
        svc = AsyncMock()
        svc.update_default_provider = AsyncMock()
        _override_service(svc)
        resp = client.put(
            "/api/llm-provider/default-provider",
            json={"defaultProvider": 2},
        )
        assert resp.status_code == 200
        svc.update_default_provider.assert_called_once()

    def test_update_default_embedding_provider(self) -> None:
        svc = AsyncMock()
        svc.update_default_embedding_provider = AsyncMock()
        _override_service(svc)
        resp = client.put(
            "/api/llm-provider/default-embedding-provider",
            json={"defaultEmbeddingProvider": 2},
        )
        assert resp.status_code == 200
        svc.update_default_embedding_provider.assert_called_once()


class TestVoiceConfig:
    def test_get_asr_config(self) -> None:
        svc = AsyncMock()
        svc.get_asr_config = AsyncMock(return_value=_asr_dto())
        _override_service(svc)
        resp = client.get("/api/llm-provider/voice/asr")
        assert resp.status_code == 200
        assert resp.json()["data"]["model"] == "qwen3-asr-flash-realtime"

    def test_update_asr_config(self) -> None:
        svc = AsyncMock()
        svc.update_asr_config = AsyncMock()
        _override_service(svc)
        resp = client.put("/api/llm-provider/voice/asr", json={"language": "en"})
        assert resp.status_code == 200
        svc.update_asr_config.assert_called_once()

    def test_get_tts_config(self) -> None:
        svc = AsyncMock()
        svc.get_tts_config = AsyncMock(return_value=_tts_dto())
        _override_service(svc)
        resp = client.get("/api/llm-provider/voice/tts")
        assert resp.status_code == 200
        assert resp.json()["data"]["voice"] == "Cherry"

    def test_update_tts_config(self) -> None:
        svc = AsyncMock()
        svc.update_tts_config = AsyncMock()
        _override_service(svc)
        resp = client.put("/api/llm-provider/voice/tts", json={"voice": "Loongstella"})
        assert resp.status_code == 200
        svc.update_tts_config.assert_called_once()

    def test_test_asr_config(self) -> None:
        svc = AsyncMock()
        svc.test_asr_config = AsyncMock(
            return_value=ProviderTestResult(
                success=True, message="ASR WebSocket 连接成功", model="qwen3-asr-flash-realtime"
            )
        )
        _override_service(svc)
        resp = client.post("/api/llm-provider/voice/asr/test")
        assert resp.status_code == 200
        assert resp.json()["data"]["success"] is True
