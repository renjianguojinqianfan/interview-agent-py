import pytest

from app.infrastructure.ai.provider_snapshot import looks_like_chat_model


class TestLooksLikeChatModel:
    @pytest.mark.parametrize(
        "model",
        ["qwen-max", "deepseek-chat", "kimi-k2", "glm-4", "moonshot-v1-8k", "ernie-4.0"],
    )
    def test_true_for_chat_models(self, model: str) -> None:
        assert looks_like_chat_model(model) is True

    def test_case_insensitive(self) -> None:
        assert looks_like_chat_model("QWEN-Max") is True

    @pytest.mark.parametrize(
        "model",
        ["text-embedding-v3", "bge-large-zh", "m3e-base"],
    )
    def test_false_for_embedding_models(self, model: str) -> None:
        assert looks_like_chat_model(model) is False
