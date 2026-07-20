import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.knowledgebase.schemas import (
    KnowledgeBaseDetailDTO,
    KnowledgeBaseInfoDTO,
    KnowledgeBaseListItemDTO,
    KnowledgeBasePageDTO,
    KnowledgeBaseUploadResponse,
    StorageInfoDTO,
)
from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.parsing.content_type import ContentTypeDetector
from app.infrastructure.parsing.parser import DocumentParser
from app.infrastructure.storage.hash import FileHashService
from app.infrastructure.storage.s3 import S3StorageService
from app.infrastructure.tasks.kb_vectorize_producer import KbVectorizePayload, VectorizeStreamProducer
from app.infrastructure.vector.repository import VectorRepository

logger = logging.getLogger(__name__)

_KB_STORAGE_PREFIX = "knowledge-bases"


class KnowledgeBaseService:
    """知识库业务编排：上传(检测->去重->解析->存储->入库->入队向量化)、列表、详情、删除、重新向量化。"""

    def __init__(
        self,
        session: AsyncSession,
        repository: KnowledgeBaseRepository,
        parser: DocumentParser,
        hash_service: FileHashService,
        content_detector: ContentTypeDetector,
        storage: S3StorageService,
        producer: VectorizeStreamProducer,
        vector_repository: VectorRepository,
        allowed_types: list[str],
        max_file_size: int,
    ) -> None:
        self._session = session
        self._repository = repository
        self._parser = parser
        self._hash_service = hash_service
        self._content_detector = content_detector
        self._storage = storage
        self._producer = producer
        self._vector_repository = vector_repository
        self._allowed_types = allowed_types
        self._max_file_size = max_file_size

    async def upload(self, filename: str, content_type: str, data: bytes) -> KnowledgeBaseUploadResponse:
        self._validate_size(data)
        detected_type = self._content_detector.detect(data, filename)
        if not self._is_allowed(detected_type):
            raise BusinessException(
                ErrorCode.KNOWLEDGE_BASE_UPLOAD_FAILED,
                f"不支持的文件类型: {detected_type}",
            )

        file_hash = self._hash_service.calculate_hash(data)
        existing = await self._repository.find_by_hash(self._session, file_hash)
        if existing is not None:
            logger.info("检测到重复知识库文件: hash=%s, knowledgeBaseId=%s", file_hash, existing.id)
            return self._build_duplicate_response(existing)

        content_text = await asyncio.to_thread(self._parser.parse_content, data, filename)
        if not content_text.strip():
            raise BusinessException(
                ErrorCode.KNOWLEDGE_BASE_PARSE_FAILED,
                "无法从文件中提取文本内容，请确保文件不是扫描版PDF",
            )

        storage_key = await self._storage.upload_file(data, filename, _KB_STORAGE_PREFIX)
        storage_url = self._storage.build_file_url(storage_key)

        kb = KnowledgeBase(
            file_hash=file_hash,
            original_filename=filename,
            file_size=len(data),
            content_type=content_type or detected_type,
            storage_key=storage_key,
            storage_url=storage_url,
            content_text=content_text,
            vector_status=AsyncTaskStatus.PENDING.value,
        )
        await self._repository.save(self._session, kb)
        await self._session.commit()
        logger.info("知识库上传完成: knowledgeBaseId=%s, filename=%s", kb.id, filename)
        await self._enqueue_vectorize(kb.id)

        return KnowledgeBaseUploadResponse(
            knowledge_base=self._to_kb_info(kb),
            storage=StorageInfoDTO(
                file_key=storage_key,
                file_url=storage_url,
                knowledge_base_id=kb.id,
            ),
            duplicate=False,
        )

    async def list_knowledge_bases(self, page: int, size: int) -> KnowledgeBasePageDTO:
        kbs, total = await self._repository.list_paginated(self._session, page, size)
        items = [
            KnowledgeBaseListItemDTO(
                id=kb.id,
                filename=kb.original_filename,
                file_size=kb.file_size,
                uploaded_at=kb.uploaded_at,
                chunk_count=kb.chunk_count,
                vector_status=kb.vector_status,
                vector_error=kb.vector_error,
                vectorized_at=kb.vectorized_at,
            )
            for kb in kbs
        ]
        return KnowledgeBasePageDTO(items=items, total=total, page=page, size=size)

    async def get_detail(self, kb_id: int) -> KnowledgeBaseDetailDTO:
        kb = await self._repository.get_by_id(self._session, kb_id)
        if kb is None:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)

        return KnowledgeBaseDetailDTO(
            id=kb.id,
            filename=kb.original_filename,
            file_size=kb.file_size,
            content_type=kb.content_type,
            storage_url=kb.storage_url,
            uploaded_at=kb.uploaded_at,
            content_text=kb.content_text,
            chunk_count=kb.chunk_count,
            vector_status=kb.vector_status,
            vector_error=kb.vector_error,
            vectorized_at=kb.vectorized_at,
        )

    async def delete(self, kb_id: int) -> None:
        kb = await self._repository.get_by_id(self._session, kb_id)
        if kb is None:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)

        if kb.storage_key:
            try:
                await self._storage.delete_file(kb.storage_key)
            except Exception as e:
                logger.warning("删除存储文件失败，继续删除数据库记录: knowledgeBaseId=%s, error=%s", kb_id, e)

        await self._vector_repository.delete_by_knowledge_base_id(self._session, kb_id)
        await self._repository.delete(self._session, kb)
        await self._session.commit()
        logger.info("知识库已删除: knowledgeBaseId=%s", kb_id)

    async def revectorize(self, kb_id: int) -> None:
        kb = await self._repository.get_by_id(self._session, kb_id)
        if kb is None:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)

        await self._repository.update_vector_status(self._session, kb, AsyncTaskStatus.PENDING.value, None)
        await self._session.commit()
        logger.info("知识库重新向量化已触发: knowledgeBaseId=%s", kb_id)
        await self._enqueue_vectorize(kb_id)

    async def _enqueue_vectorize(self, kb_id: int) -> None:
        await self._producer.send_task(KbVectorizePayload(knowledge_base_id=kb_id))

    def _validate_size(self, data: bytes) -> None:
        if len(data) > self._max_file_size:
            raise BusinessException(
                ErrorCode.KNOWLEDGE_BASE_UPLOAD_FAILED,
                f"文件大小超过限制: {len(data)} > {self._max_file_size}",
            )

    def _is_allowed(self, content_type: str) -> bool:
        return content_type in self._allowed_types

    def _build_duplicate_response(self, kb: KnowledgeBase) -> KnowledgeBaseUploadResponse:
        return KnowledgeBaseUploadResponse(
            knowledge_base=self._to_kb_info(kb),
            storage=StorageInfoDTO(
                file_key=kb.storage_key or "",
                file_url=kb.storage_url or "",
                knowledge_base_id=kb.id,
            ),
            duplicate=True,
        )

    def _to_kb_info(self, kb: KnowledgeBase) -> KnowledgeBaseInfoDTO:
        return KnowledgeBaseInfoDTO(
            id=kb.id,
            filename=kb.original_filename,
            vector_status=kb.vector_status,
        )
