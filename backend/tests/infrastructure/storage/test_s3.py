from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.storage.s3 import S3StorageService


def _make_mock_s3_client() -> MagicMock:
    client = MagicMock()
    client.put_object = AsyncMock()
    client.get_object = AsyncMock()
    client.delete_object = AsyncMock()
    client.head_object = AsyncMock()
    return client


class _FakeClientContext:
    """把 mock client 包成可 async with 的上下文，模拟 aioboto3 ClientCreatorContext 的进入语义。"""

    def __init__(self, client: MagicMock) -> None:
        self._client = client

    async def __aenter__(self) -> MagicMock:
        return self._client

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.fixture()
def mock_client() -> MagicMock:
    return _make_mock_s3_client()


@pytest.fixture()
def service(mock_client: MagicMock) -> S3StorageService:
    def _factory() -> Any:
        return _FakeClientContext(mock_client)

    return S3StorageService(client_factory=_factory, bucket="test-bucket")


class TestUploadFile:
    async def test_returns_storage_key_with_prefix(self, service: S3StorageService) -> None:
        key = await service.upload_file(b"file content", "resume.pdf", "resumes")
        assert key.startswith("resumes/")
        assert "resume.pdf" in key

    async def test_key_contains_date_path(self, service: S3StorageService) -> None:
        from datetime import UTC, datetime

        key = await service.upload_file(b"data", "doc.pdf", "resumes")
        now = datetime.now(UTC)
        date_path = f"{now.year}/{now.month:02d}/{now.day:02d}"
        assert date_path in key

    async def test_key_contains_uuid(self, service: S3StorageService) -> None:
        key = await service.upload_file(b"data", "doc.pdf", "resumes")
        parts = key.split("/")
        filename_part = parts[-1]
        uuid_part = filename_part.split("_")[0]
        assert len(uuid_part) == 36  # full UUID format

    async def test_chinese_filename_converted_to_pinyin(self, service: S3StorageService) -> None:
        key = await service.upload_file(b"data", "张三简历.pdf", "resumes")
        assert "ZhangSanJianLi.pdf" in key or "ZhangSanJianLi" in key
        assert "张" not in key

    async def test_calls_put_object(self, service: S3StorageService, mock_client: MagicMock) -> None:
        await service.upload_file(b"content", "file.txt", "docs")
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Body"] == b"content"

    async def test_upload_failure_raises(self, service: S3StorageService, mock_client: MagicMock) -> None:
        mock_client.put_object.side_effect = Exception("S3 error")
        with pytest.raises(BusinessException) as exc_info:
            await service.upload_file(b"data", "file.txt", "docs")
        assert exc_info.value.error_code == ErrorCode.STORAGE_UPLOAD_FAILED


class TestDownloadFile:
    async def test_returns_file_bytes(self, service: S3StorageService, mock_client: MagicMock) -> None:
        mock_response = {"Body": MagicMock()}
        mock_response["Body"].read = AsyncMock(return_value=b"file content")
        mock_client.get_object.return_value = mock_response

        result = await service.download_file("docs/2026/07/15/abc_file.txt")
        assert result == b"file content"

    async def test_download_failure_raises(self, service: S3StorageService, mock_client: MagicMock) -> None:
        mock_client.get_object.side_effect = Exception("S3 error")
        with pytest.raises(BusinessException) as exc_info:
            await service.download_file("nonexistent")
        assert exc_info.value.error_code == ErrorCode.STORAGE_DOWNLOAD_FAILED


class TestDeleteFile:
    async def test_calls_delete_object(self, service: S3StorageService, mock_client: MagicMock) -> None:
        mock_client.head_object.return_value = MagicMock()
        await service.delete_file("docs/2026/07/15/abc_file.txt")
        mock_client.delete_object.assert_called_once()

    async def test_skips_when_file_not_exists(self, service: S3StorageService, mock_client: MagicMock) -> None:
        mock_client.head_object.side_effect = Exception("not found")
        await service.delete_file("nonexistent")
        mock_client.delete_object.assert_not_called()

    async def test_empty_key_skips(self, service: S3StorageService, mock_client: MagicMock) -> None:
        await service.delete_file("")
        mock_client.delete_object.assert_not_called()


class TestFileExists:
    async def test_returns_true_when_exists(self, service: S3StorageService, mock_client: MagicMock) -> None:
        mock_client.head_object.return_value = MagicMock()
        assert await service.file_exists("some/key") is True

    async def test_returns_false_when_not_found(self, service: S3StorageService, mock_client: MagicMock) -> None:
        mock_client.head_object.side_effect = Exception("not found")
        assert await service.file_exists("nonexistent") is False


class TestBuildFileUrl:
    def test_builds_url_from_endpoint_bucket_and_key(self, service: S3StorageService) -> None:
        url = service.build_file_url("resumes/2026/07/15/uuid_resume.pdf")
        assert url == "http://localhost:9000/test-bucket/resumes/2026/07/15/uuid_resume.pdf"

    def test_empty_key_returns_empty(self, service: S3StorageService) -> None:
        assert service.build_file_url("") == ""
