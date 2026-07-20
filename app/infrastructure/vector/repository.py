import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import BusinessException, ErrorCode

logger = logging.getLogger(__name__)


@dataclass
class VectorItem:
    content: str
    embedding: list[float]
    metadata: dict[str, Any] | None = field(default=None)


@dataclass
class SearchResult:
    content: str
    score: float
    kb_id: int


class VectorRepository:
    async def search(
        self,
        session: AsyncSession,
        query_embedding: list[float],
        kb_ids: list[int],
        top_k: int,
    ) -> list[SearchResult]:
        """在指定知识库范围内做 pgvector 余弦相似度检索，返回按相似度降序的片段。"""
        if not kb_ids or top_k <= 0:
            return []

        vec = "[" + ",".join(str(v) for v in query_embedding) + "]"
        sql = text(
            "SELECT content, (metadata->>'kb_id') AS kb_id, "
            "1 - (embedding <=> CAST(:vec AS vector)) AS score "
            "FROM vector_store "
            "WHERE metadata->>'kb_id' = ANY(:kb_ids) "
            "ORDER BY embedding <=> CAST(:vec AS vector) ASC "
            "LIMIT :top_k"
        )

        try:
            result = await session.execute(
                sql,
                {"vec": vec, "kb_ids": [str(k) for k in kb_ids], "top_k": top_k},
            )
            rows = result.mappings().all()
            return [
                SearchResult(
                    content=row["content"] or "",
                    score=float(row["score"]),
                    kb_id=int(row["kb_id"]),
                )
                for row in rows
            ]
        except Exception as e:
            logger.error("向量检索失败: kbIds=%s, error=%s", kb_ids, e)
            raise BusinessException(
                ErrorCode.KNOWLEDGE_BASE_QUERY_FAILED,
                f"向量检索失败: {e}",
            ) from e

    async def insert_pending(
        self,
        session: AsyncSession,
        job_id: str,
        kb_id: int,
        items: list[VectorItem],
    ) -> int:
        if not items:
            return 0

        sql = text(
            "INSERT INTO vector_store (content, metadata, embedding) "
            "VALUES (:content, CAST(:metadata AS jsonb), CAST(:embedding AS vector))"
        )

        try:
            for item in items:
                metadata: dict[str, Any] = {
                    "kb_vector_job_id": job_id,
                    "kb_target_id": str(kb_id),
                }
                if item.metadata:
                    metadata.update(item.metadata)

                embedding_str = "[" + ",".join(str(v) for v in item.embedding) + "]"
                await session.execute(
                    sql,
                    {
                        "content": item.content,
                        "metadata": json.dumps(metadata),
                        "embedding": embedding_str,
                    },
                )
            logger.info("插入待定向量: jobId=%s, kbId=%s, count=%d", job_id, kb_id, len(items))
            return len(items)
        except Exception as e:
            logger.error("插入向量失败: jobId=%s, error=%s", job_id, e)
            raise BusinessException(
                ErrorCode.KNOWLEDGE_BASE_VECTORIZATION_FAILED,
                f"插入向量数据失败: {e}",
            ) from e

    async def promote_vector_job(
        self,
        session: AsyncSession,
        kb_id: int,
        job_id: str,
    ) -> int:
        sql = text(
            "UPDATE vector_store "
            "SET metadata = jsonb_set("
            "    metadata::jsonb, "
            "    '{kb_id}', "
            "    to_jsonb(:kb_id::text), "
            "    true"
            ") - 'kb_vector_job_id' - 'kb_target_id' "
            "WHERE metadata->>'kb_vector_job_id' = :job_id"
        )

        try:
            result = await session.execute(sql, {"kb_id": str(kb_id), "job_id": job_id})
            updated = getattr(result, "rowcount", 0) or 0
            logger.info("提升临时向量为正式数据: kbId=%s, jobId=%s, 更新行数=%d", kb_id, job_id, updated)
            return updated
        except Exception as e:
            logger.error("提升向量失败: kbId=%s, jobId=%s, error=%s", kb_id, job_id, e)
            raise BusinessException(
                ErrorCode.KNOWLEDGE_BASE_VECTORIZATION_FAILED,
                "提升临时向量数据失败",
            ) from e

    async def delete_by_knowledge_base_id(
        self,
        session: AsyncSession,
        kb_id: int,
    ) -> int:
        sql = text("DELETE FROM vector_store WHERE metadata->>'kb_id' = :kb_id")

        try:
            result = await session.execute(sql, {"kb_id": str(kb_id)})
            deleted = getattr(result, "rowcount", 0) or 0
            logger.info("删除知识库向量: kbId=%s, 删除行数=%d", kb_id, deleted)
            return deleted
        except Exception as e:
            logger.error("删除向量失败: kbId=%s, error=%s", kb_id, e)
            raise BusinessException(
                ErrorCode.KNOWLEDGE_BASE_DELETE_FAILED,
                "删除向量数据失败",
            ) from e

    async def delete_by_vector_job_id(
        self,
        session: AsyncSession,
        job_id: str,
    ) -> int:
        sql = text("DELETE FROM vector_store WHERE metadata->>'kb_vector_job_id' = :job_id")

        try:
            result = await session.execute(sql, {"job_id": job_id})
            deleted = getattr(result, "rowcount", 0) or 0
            logger.info("清理临时向量: jobId=%s, 删除行数=%d", job_id, deleted)
            return deleted
        except Exception as e:
            logger.error("清理临时向量失败: jobId=%s, error=%s", job_id, e)
            raise BusinessException(
                ErrorCode.KNOWLEDGE_BASE_VECTORIZATION_FAILED,
                "清理临时向量数据失败",
            ) from e
