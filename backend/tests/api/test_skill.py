"""技能管理 API 路由测试。"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_skill_service
from app.api.rate_limit import limiter
from app.application.skill.schemas import (
    CategoryDTO,
    DisplayDTO,
    SkillCategoryDTO,
    SkillDTO,
)
from app.domain.errors import BusinessException, ErrorCode
from app.main import app

client = TestClient(app)


def _skill_dto(skill_id: str = "java-backend") -> SkillDTO:
    return SkillDTO(
        id=skill_id,
        name="Java 后端开发",
        description="Java 后端面试",
        categories=[
            SkillCategoryDTO(key="JAVA", label="Java", priority="CORE", ref="java.md", shared=True),
            SkillCategoryDTO(key="PROJECT", label="项目", priority="ALWAYS_ONE"),
        ],
        is_preset=True,
        display=DisplayDTO(icon="☕", gradient="from-blue-500 to-indigo-500"),
    )


def _mock_service() -> MagicMock:
    service = MagicMock()
    service.list_skills = AsyncMock()
    service.get_skill = AsyncMock()
    service.parse_jd = AsyncMock()
    return service


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def mock_service() -> Iterator[MagicMock]:
    service = _mock_service()
    app.dependency_overrides[get_skill_service] = lambda: service
    yield service
    app.dependency_overrides.pop(get_skill_service, None)


class TestListSkills:
    def test_returns_list(self, mock_service: MagicMock) -> None:
        mock_service.list_skills.return_value = [_skill_dto() for _ in range(10)]
        resp = client.get("/api/interview/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert len(body["data"]) == 10
        assert body["data"][0]["id"] == "java-backend"
        assert body["data"][0]["isPreset"] is True
        assert body["data"][0]["display"]["icon"] == "☕"

    def test_empty_list(self, mock_service: MagicMock) -> None:
        mock_service.list_skills.return_value = []
        resp = client.get("/api/interview/skills")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestGetSkill:
    def test_found(self, mock_service: MagicMock) -> None:
        mock_service.get_skill.return_value = _skill_dto("python-backend")
        resp = client.get("/api/interview/skills/python-backend")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == "python-backend"

    def test_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_skill.side_effect = BusinessException(ErrorCode.SKILL_NOT_FOUND, "未找到面试主题: unknown")
        resp = client.get("/api/interview/skills/unknown")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == ErrorCode.SKILL_NOT_FOUND.code


class TestParseJd:
    def test_success(self, mock_service: MagicMock) -> None:
        mock_service.parse_jd.return_value = [
            CategoryDTO(key="JAVA", label="Java", priority="CORE", ref="java.md", shared=True),
        ]
        resp = client.post(
            "/api/interview/skills/parse-jd",
            json={"jdText": "我们需要一位 Java 后端工程师，熟悉 Spring Boot 和 MySQL。"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200
        assert len(body["data"]) == 1
        assert body["data"][0]["key"] == "JAVA"
        assert body["data"][0]["ref"] == "java.md"

    def test_too_short(self, mock_service: MagicMock) -> None:
        mock_service.parse_jd.side_effect = BusinessException(ErrorCode.BAD_REQUEST, "JD 内容太少")
        resp = client.post(
            "/api/interview/skills/parse-jd",
            json={"jdText": "短"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == ErrorCode.BAD_REQUEST.code

    def test_missing_field(self, mock_service: MagicMock) -> None:
        resp = client.post("/api/interview/skills/parse-jd", json={})
        assert resp.status_code == 200
        assert resp.json()["code"] == ErrorCode.BAD_REQUEST.code
