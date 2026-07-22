import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.knowledgebase.schemas import (
    KnowledgeBaseInfoDTO,
    KnowledgeBaseListItemDTO,
    KnowledgeBaseStatsDTO,
    KnowledgeBaseUploadResponse,
    StorageInfoDTO,
)
from app.domain.entities.task_status import AsyncTaskStatus
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.knowledge_base import KnowledgeBase
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.db.repositories.rag_chat_repository import RagChatRepository
from app.infrastructure.parsing.content_type import ContentTypeDetector
from app.infrastructure.parsing.parser import DocumentParser
from app.infrastructure.storage.hash import FileHashService
from app.infrastructure.storage.s3 import S3StorageService
from app.infrastructure.tasks.kb_vectorize_producer import KbVectorizePayload, VectorizeStreamProducer
from app.infrastructure.vector.repository import VectorRepository

logger = logging.getLogger(__name__)

_KB_STORAGE_PREFIX = "knowledge-bases"
_USER_MESSAGE_ROLE = "user"


def _normalize_category(category: str | None) -> str | None:
    """空白分类归一为 None（对齐 Java KnowledgeBaseListService 的 isBlank() 语义）。"""
    return category if category and category.strip() else None


class KnowledgeBaseService:
    """知识库业务编排：上传(检测->去重->解析->存储->入库->入队向量化)、列表、详情、删除、重新向量化。"""

    def __init__(
        self,
        session: AsyncSession,
        repository: KnowledgeBaseRepository,
        rag_repository: RagChatRepository,
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
        self._rag_repository = rag_repository
        self._parser = parser
        self._hash_service = hash_service
        self._content_detector = content_detector
        self._storage = storage
        self._producer = producer
        self._vector_repository = vector_repository
        self._allowed_types = allowed_types
        self._max_file_size = max_file_size

    async def upload(
        self,
        filename: str,
        content_type: str,
        data: bytes,
        name: str | None = None,
        category: str | None = None,
    ) -> KnowledgeBaseUploadResponse:
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
            name=name or filename,
            category=category or None,
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

    async def list_knowledge_bases(
        self, sort_by: str | None = None, vector_status: str | None = None
    ) -> list[KnowledgeBaseListItemDTO]:
        kbs = await self._repository.list_all(self._session, vector_status)
        return [self._to_list_item(kb) for kb in self._sort(kbs, sort_by)]

    async def list_by_category(self, category: str | None) -> list[KnowledgeBaseListItemDTO]:
        kbs = await self._repository.list_by_category(self._session, _normalize_category(category))
        return [self._to_list_item(kb) for kb in kbs]

    async def list_categories(self) -> list[str]:
        return await self._repository.list_categories(self._session)

    async def search(self, keyword: str) -> list[KnowledgeBaseListItemDTO]:
        if not keyword or not keyword.strip():
            return await self.list_knowledge_bases()
        kbs = await self._repository.search(self._session, keyword.strip())
        return [self._to_list_item(kb) for kb in kbs]

    async def update_category(self, kb_id: int, category: str | None) -> None:
        kb = await self._repository.get_by_id(self._session, kb_id)
        if kb is None:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)
        normalized = _normalize_category(category)
        await self._repository.update_category(self._session, kb, normalized)
        await self._session.commit()
        logger.info("更新知识库分类: knowledgeBaseId=%s, category=%s", kb_id, normalized)

    async def get_statistics(self) -> KnowledgeBaseStatsDTO:
        total_count = await self._repository.count_all(self._session)
        total_access_count = await self._repository.sum_access_count(self._session)
        completed_count = await self._repository.count_by_vector_status(self._session, AsyncTaskStatus.COMPLETED.value)
        processing_count = await self._repository.count_by_vector_status(
            self._session, AsyncTaskStatus.PROCESSING.value
        )
        # 总提问次数以 RAG 用户消息计（多知识库提问只算一次），对齐 Java KnowledgeBaseListService.getStatistics。
        total_question_count = await self._rag_repository.count_messages_by_role(self._session, _USER_MESSAGE_ROLE)
        return KnowledgeBaseStatsDTO(
            total_count=total_count,
            total_question_count=total_question_count,
            total_access_count=total_access_count,
            completed_count=completed_count,
            processing_count=processing_count,
        )

    async def download(self, kb_id: int) -> tuple[bytes, str, str | None]:
        kb = await self._repository.get_by_id(self._session, kb_id)
        if kb is None:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_NOT_FOUND)
        if not kb.storage_key:
            raise BusinessException(ErrorCode.STORAGE_DOWNLOAD_FAILED, "文件存储信息不存在")
        data = await self._storage.download_file(kb.storage_key)
        return data, kb.original_filename, kb.content_type

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

    def _sort(self, kbs: list[KnowledgeBase], sort_by: str | None) -> list[KnowledgeBase]:
        """内存排序，对齐 Java KnowledgeBaseListService.sortEntities（time 走库层已排序）。"""
        if not sort_by or sort_by.lower() == "time":
            return kbs
        key = sort_by.lower()
        if key == "size":
            return sorted(kbs, key=lambda kb: kb.file_size or 0, reverse=True)
        if key == "access":
            return sorted(kbs, key=lambda kb: kb.access_count, reverse=True)
        if key == "question":
            return sorted(kbs, key=lambda kb: kb.question_count, reverse=True)
        return kbs

    def _to_list_item(self, kb: KnowledgeBase) -> KnowledgeBaseListItemDTO:
        return KnowledgeBaseListItemDTO(
            id=kb.id,
            name=kb.name or kb.original_filename,
            category=kb.category,
            original_filename=kb.original_filename,
            file_size=kb.file_size,
            content_type=kb.content_type,
            uploaded_at=kb.uploaded_at,
            last_accessed_at=kb.last_accessed_at or kb.uploaded_at,
            access_count=kb.access_count,
            question_count=kb.question_count,
            vector_status=kb.vector_status,
            vector_error=kb.vector_error,
            chunk_count=kb.chunk_count,
        )
