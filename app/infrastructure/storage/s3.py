import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pypinyin import Style, lazy_pinyin

from app.config.settings import settings
from app.domain.errors import BusinessException, ErrorCode

logger = logging.getLogger(__name__)

_SAFE_CHAR_RE = re.compile(r"[^a-zA-Z0-9._\-]")


class S3StorageService:
    def __init__(self, client: Any = None, bucket: str | None = None) -> None:
        self._client = client
        self._bucket = bucket or settings.s3_bucket

    async def upload_file(self, data: bytes, filename: str, prefix: str) -> str:
        key = self._generate_file_key(filename, prefix)
        try:
            await self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
            logger.info("文件上传成功: %s -> %s", filename, key)
            return key
        except Exception as e:
            logger.error("上传文件失败: %s, error=%s", filename, e)
            raise BusinessException(
                ErrorCode.STORAGE_UPLOAD_FAILED,
                f"文件存储失败: {e}",
            ) from e

    async def download_file(self, key: str) -> bytes:
        try:
            response = await self._client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"]
            data: bytes = await body.read()
            return data
        except Exception as e:
            logger.error("下载文件失败: %s, error=%s", key, e)
            raise BusinessException(
                ErrorCode.STORAGE_DOWNLOAD_FAILED,
                f"文件下载失败: {e}",
            ) from e

    async def delete_file(self, key: str) -> None:
        if not key:
            return
        if not await self.file_exists(key):
            logger.warning("文件不存在，跳过删除: %s", key)
            return
        try:
            await self._client.delete_object(Bucket=self._bucket, Key=key)
            logger.info("文件删除成功: %s", key)
        except Exception as e:
            logger.error("删除文件失败: %s, error=%s", key, e)
            raise BusinessException(
                ErrorCode.STORAGE_DELETE_FAILED,
                f"文件删除失败: {e}",
            ) from e

    async def file_exists(self, key: str) -> bool:
        try:
            await self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    def build_file_url(self, key: str) -> str:
        if not key:
            return ""
        return f"{settings.s3_endpoint}/{self._bucket}/{key}"

    def _generate_file_key(self, filename: str, prefix: str) -> str:
        date_path = datetime.now(UTC).strftime("%Y/%m/%d")
        file_uuid = str(uuid.uuid4())
        safe_name = self._sanitize_filename(filename)
        return f"{prefix}/{date_path}/{file_uuid}_{safe_name}"

    def _sanitize_filename(self, filename: str) -> str:
        if not filename:
            return "unknown"

        result: list[str] = []
        for char in filename:
            pinyins = lazy_pinyin(char, style=Style.NORMAL)
            if pinyins and pinyins[0] != char:
                result.append(pinyins[0].capitalize())
            else:
                result.append(char)

        joined = "".join(result)
        return _SAFE_CHAR_RE.sub("_", joined)


def create_s3_client() -> Any:
    import aioboto3  # type: ignore[import-untyped]

    session = aioboto3.Session()
    return session.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


def create_s3_storage_service() -> S3StorageService:
    return S3StorageService(client=create_s3_client(), bucket=settings.s3_bucket)
