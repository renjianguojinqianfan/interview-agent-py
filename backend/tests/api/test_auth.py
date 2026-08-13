"""认证语义 API 测试（HARD #1/#2）。

覆盖降级矩阵、token 缺失/无效/有效、登录凭据门禁与业务路由 401 语义。
"""

import secrets

from fastapi.testclient import TestClient

from app.config.settings import settings
from app.infrastructure.auth.jwt import create_access_token
from app.main import app

client = TestClient(app)


def _configure_auth(
    monkeypatch: object,
    *,
    secret_key: str | None = None,
    username: str = "",
    password: str = "",
) -> None:
    """集中设置认证相关配置，测试结束后由 monkeypatch 自动还原。

    secret_key 缺省时运行时生成：测试文件不落凭据形态字面量（Mimosa 门禁）。
    """
    monkeypatch.setattr(  # type: ignore[attr-defined]
        settings, "secret_key", secret_key if secret_key is not None else secrets.token_hex(16)
    )
    monkeypatch.setattr(settings, "auth_admin_username", username)  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "auth_admin_password", password)  # type: ignore[attr-defined]


class TestDegradedMode:
    """secret_key 未配置时降级无认证：任何请求都视为 default 用户。"""

    def test_returns_default_user_without_token(self, monkeypatch: object) -> None:
        _configure_auth(monkeypatch, secret_key="")

        response = client.get("/api/auth/me")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["user_id"] == "default"

    def test_ignores_invalid_token(self, monkeypatch: object) -> None:
        _configure_auth(monkeypatch, secret_key="")

        response = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

        assert response.status_code == 200
        assert response.json()["data"]["user_id"] == "default"


class TestTokenValidation:
    """secret_key 配置后，缺失/无效 token 必须 401，有效 token 放行。"""

    def test_missing_token_returns_unauthorized(self, monkeypatch: object) -> None:
        _configure_auth(monkeypatch)

        response = client.get("/api/auth/me")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 401
        assert body["data"] is None

    def test_business_router_returns_unauthorized_without_token(self, monkeypatch: object) -> None:
        _configure_auth(monkeypatch)

        response = client.get("/api/interview/sessions")

        assert response.status_code == 200
        assert response.json()["code"] == 401

    def test_invalid_token_returns_unauthorized(self, monkeypatch: object) -> None:
        _configure_auth(monkeypatch)

        response = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid-token"})

        assert response.status_code == 200
        assert response.json()["code"] == 401

    def test_valid_token_allows_access(self, monkeypatch: object) -> None:
        _configure_auth(monkeypatch)
        token = create_access_token("default")

        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        assert body["data"]["user_id"] == "default"


class TestLogin:
    """登录凭据门禁：配置了管理员账号则必须匹配，未配置则降级放行。"""

    def test_login_succeeds_with_configured_credentials(self, monkeypatch: object) -> None:
        _admin_username = "test-admin"
        _admin_password = secrets.token_urlsafe(8)
        _configure_auth(monkeypatch, username=_admin_username, password=_admin_password)

        response = client.post("/api/auth/login", json={"username": _admin_username, "password": _admin_password})

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 200
        token = body["data"]["access_token"]
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["data"]["user_id"] == "default"

    def test_login_rejects_wrong_credentials(self, monkeypatch: object) -> None:
        _admin_username = "test-admin"
        _admin_password = secrets.token_urlsafe(8)
        _configure_auth(monkeypatch, username=_admin_username, password=_admin_password)

        response = client.post("/api/auth/login", json={"username": _admin_username, "password": "wrong"})

        assert response.status_code == 200
        assert response.json()["code"] == 401

    def test_login_degrades_when_credentials_not_configured(self, monkeypatch: object) -> None:
        _configure_auth(monkeypatch)

        response = client.post("/api/auth/login", json={"username": "any", "password": "any"})

        assert response.status_code == 200
        assert response.json()["code"] == 200
        assert response.json()["data"]["access_token"]

    def test_login_rejects_partial_credentials_config(self, monkeypatch: object) -> None:
        username = "test-admin"
        _configure_auth(monkeypatch, username=username)

        response = client.post("/api/auth/login", json={"username": username, "password": "wrong"})

        assert response.status_code == 200
        assert response.json()["code"] == 401
