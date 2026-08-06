"""限流测试：IP 多级 fallback 单元测试（migration-plan 8.2）+ login 端点限流行为测试（SEC-03）。"""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.api.rate_limit import client_ip, limiter
from app.config.settings import settings
from app.main import app

client = TestClient(app)


def _request(headers: dict[str, str], client_host: str | None = "10.0.0.1") -> MagicMock:
    req = MagicMock()
    req.headers = Headers(headers)
    if client_host is None:
        req.client = None
    else:
        req.client = MagicMock()
        req.client.host = client_host
    return req


class TestClientIp:
    def test_prefers_x_forwarded_for_leftmost_ip(self) -> None:
        req = _request({"X-Forwarded-For": "1.1.1.1, 2.2.2.2", "X-Real-IP": "3.3.3.3"})
        assert client_ip(req) == "1.1.1.1"

    def test_falls_back_to_x_real_ip(self) -> None:
        req = _request({"X-Real-IP": "3.3.3.3", "Proxy-Client-IP": "4.4.4.4"})
        assert client_ip(req) == "3.3.3.3"

    def test_falls_back_to_proxy_client_ip(self) -> None:
        req = _request({"Proxy-Client-IP": "4.4.4.4"})
        assert client_ip(req) == "4.4.4.4"

    def test_falls_back_to_remote_addr_when_no_headers(self) -> None:
        req = _request({}, client_host="10.0.0.1")
        assert client_ip(req) == "10.0.0.1"

    def test_ignores_empty_or_blank_header_and_continues_chain(self) -> None:
        req = _request({"X-Forwarded-For": "  ", "X-Real-IP": "3.3.3.3"})
        assert client_ip(req) == "3.3.3.3"

    def test_case_insensitive_header_lookup(self) -> None:
        req = _request({"x-forwarded-for": "9.9.9.9"})
        assert client_ip(req) == "9.9.9.9"


class TestLoginRateLimit:
    """SEC-03：/api/auth/login 必须按 IP 限流（5/min），防暴力破解管理员凭据。"""

    @pytest.fixture(autouse=True)
    def _reset_limiter(self) -> Iterator[None]:
        """清空 slowapi 单例内存计数器，隔离测试间状态。"""
        limiter.reset()
        yield
        limiter.reset()

    @staticmethod
    def _configure_auth(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "secret_key", "test-secret-key-0123456789abcdef")
        monkeypatch.setattr(settings, "auth_admin_username", "admin")
        monkeypatch.setattr(settings, "auth_admin_password", "secret")

    def test_login_blocked_after_5_requests_per_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._configure_auth(monkeypatch)

        for _ in range(5):
            response = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
            assert response.status_code == 200
            assert response.json()["code"] == 200

        response = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
        assert response.status_code == 200
        assert response.json()["code"] == 8001
