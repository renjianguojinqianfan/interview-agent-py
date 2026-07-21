"""限流 IP 获取多级 fallback 测试（migration-plan 8.2）。"""

from unittest.mock import MagicMock

from starlette.datastructures import Headers

from app.api.rate_limit import client_ip


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
