"""上传大小双段校验单元测试（ST-02/SEC-05：Content-Length 先于 read() 校验，防内存 DoS）。"""

import pytest
from fastapi import HTTPException, Request

from app.api.uploads import check_upload_size


def _request(content_length: str | None) -> Request:
    headers = [(b"content-length", content_length.encode())] if content_length else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


class TestCheckUploadSize:
    def test_raises_413_when_header_exceeds_max(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            check_upload_size(_request("99999999"), max_bytes=1024)

        assert exc_info.value.status_code == 413

    def test_passes_when_header_within_max(self) -> None:
        check_upload_size(_request("512"), max_bytes=1024)

    def test_passes_when_header_missing(self) -> None:
        check_upload_size(_request(None), max_bytes=1024)

    def test_ignores_invalid_header(self) -> None:
        check_upload_size(_request("abc"), max_bytes=1024)

    def test_raises_413_when_actual_data_exceeds_max(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            check_upload_size(_request(None), max_bytes=1024, data=b"x" * 2048)

        assert exc_info.value.status_code == 413

    def test_passes_when_actual_data_within_max(self) -> None:
        check_upload_size(_request("512"), max_bytes=1024, data=b"tiny")

    def test_actual_data_fallback_when_header_underreports(self) -> None:
        # 头未超限但实际数据超限（头伪造/under-report）：读后兜底拦截
        with pytest.raises(HTTPException) as exc_info:
            check_upload_size(_request("512"), max_bytes=1024, data=b"x" * 2048)

        assert exc_info.value.status_code == 413
