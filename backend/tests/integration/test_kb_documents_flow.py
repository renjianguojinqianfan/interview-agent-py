"""知识库多文档集成竖切（ADR-0018，issue #52 / issue59a）：真 HTTP -> 真解析 -> 真 S3 -> 真库。

覆盖"一库多文档"的核心承诺：向同一知识库追加第二个文件不再覆盖第一个
（documents 表两行、KB 行文件级字段为 None），文档列表可见、删除单文档不伤及其余。
同时验证 issue59a 去双写 + file_hash UNIQUE 解耦后的跨库同文件上传。
"""

import asyncio
import socket
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import settings
from app.infrastructure.db.models.knowledge_base import KnowledgeBase, KnowledgeBaseDocument


@pytest.fixture(autouse=True)
def _require_object_store() -> None:
    """依赖对象存储(MinIO)；端口不可达则 skip（与 test_upload_pipelines 同惯例）。"""
    parsed = urlparse(settings.s3_endpoint)
    host = parsed.hostname or "localhost"
    port = parsed.port or 9000
    try:
        with socket.create_connection((host, port), timeout=1):
            return
    except OSError:
        pytest.skip(f"对象存储不可达({settings.s3_endpoint})：docker compose up -d minio createbuckets")


def _load_state() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    async def _run() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        engine = create_async_engine(settings.database_url)
        try:
            async with AsyncSession(engine) as db:
                kbs = (await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.id))).scalars().all()
                docs = (
                    (await db.execute(select(KnowledgeBaseDocument).order_by(KnowledgeBaseDocument.id))).scalars().all()
                )
                return (
                    [
                        {
                            "id": kb.id,
                            "content_text": kb.content_text,
                            "file_size": kb.file_size,
                            "content_type": kb.content_type,
                            "storage_key": kb.storage_key,
                            "storage_url": kb.storage_url,
                            "vector_status": kb.vector_status,
                        }
                        for kb in kbs
                    ],
                    [
                        {
                            "id": d.id,
                            "kb_id": d.knowledge_base_id,
                            "filename": d.original_filename,
                            "content_text": d.content_text,
                            "file_size": d.file_size,
                            "vector_status": d.vector_status,
                        }
                        for d in docs
                    ],
                )
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_kb_multi_document_append_list_delete(integration_client: TestClient) -> None:
    """追加第二个文件不覆盖第一个；列表可见两行；删除单文档不伤及其余。"""
    # 1. 上传建库（首文档双写）
    first = "第一份文档：Java 线程池核心参数与拒绝策略。".encode()
    resp = integration_client.post(
        "/api/knowledgebase/upload",
        files={"file": ("first.txt", first, "text/plain")},
        data={"name": "多文档库", "category": "Java"},
    )
    assert resp.status_code == 200
    kb_id = resp.json()["data"]["knowledgeBase"]["id"]

    # 2. 追加第二个文件（POST /{kb_id}/documents）
    second = "第二份文档：volatile 可见性与内存屏障。".encode()
    resp = integration_client.post(
        f"/api/knowledgebase/{kb_id}/documents",
        files={"file": ("second.md", second, "text/markdown")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    doc2_id = body["data"]["id"]
    assert body["data"]["knowledgeBaseId"] == kb_id
    assert body["data"]["vectorStatus"] == "PENDING"

    # 3. 真库断言：documents 两行，KB 行文件级字段已清空（issue59a 去双写）
    kbs, docs = _load_state()
    assert len(kbs) == 1
    assert kbs[0]["content_text"] is None  # KB 行不再双写 content_text
    assert kbs[0]["file_size"] is None  # KB 行不再写 file_size
    assert kbs[0]["content_type"] is None  # KB 行不再写 content_type
    assert kbs[0]["storage_key"] is None  # KB 行不再写 storage_key
    assert kbs[0]["storage_url"] is None  # KB 行不再写 storage_url
    assert len(docs) == 2
    assert {d["filename"] for d in docs} == {"first.txt", "second.md"}
    assert "第二份文档" in str(docs[1]["content_text"])
    # Document 行正确承载文件级字段
    assert docs[0]["file_size"] is not None and docs[0]["file_size"] > 0
    assert docs[1]["file_size"] is not None and docs[1]["file_size"] > 0

    # 4. 文档列表端点
    resp = integration_client.get(f"/api/knowledgebase/{kb_id}/documents")
    listed = resp.json()["data"]
    assert [d["originalFilename"] for d in listed] == ["first.txt", "second.md"]

    # 5. 同库重复文件被拒（同 hash）
    resp = integration_client.post(
        f"/api/knowledgebase/{kb_id}/documents",
        files={"file": ("second-copy.md", second, "text/markdown")},
    )
    assert resp.json()["code"] != 200

    # 6. 删除第二个文档：第一个文档与 KB 完好
    resp = integration_client.delete(f"/api/knowledgebase/{kb_id}/documents/{doc2_id}")
    assert resp.json()["code"] == 200
    kbs, docs = _load_state()
    assert len(docs) == 1
    assert docs[0]["filename"] == "first.txt"
    assert len(kbs) == 1


def test_cross_kb_same_file_both_succeed(integration_client: TestClient) -> None:
    """issue59a：跨库上传相同文件各自成功（file_hash UNIQUE 约束已从 KB 行移除）。

    旧设计：knowledge_bases.file_hash UNIQUE → 跨库同文件被拒。
    新设计：file_hash 仅在 documents 表按 (kb_id, file_hash) 唯一，跨库允许。
    """
    payload = "跨库共享的同一份文件内容：JVM 内存模型与 happens-before。".encode()

    # 1. 上传到第一个知识库
    resp1 = integration_client.post(
        "/api/knowledgebase/upload",
        files={"file": ("shared.txt", payload, "text/plain")},
        data={"name": "知识库A", "category": "Java"},
    )
    assert resp1.status_code == 200
    kb_a_id = resp1.json()["data"]["knowledgeBase"]["id"]

    # 2. 上传相同文件到第二个知识库 —— 应成功（不再被 file_hash UNIQUE 拒绝）
    resp2 = integration_client.post(
        "/api/knowledgebase/upload",
        files={"file": ("shared.txt", payload, "text/plain")},
        data={"name": "知识库B", "category": "Java"},
    )
    assert resp2.status_code == 200
    kb_b_id = resp2.json()["data"]["knowledgeBase"]["id"]
    assert kb_a_id != kb_b_id

    # 3. 真库断言：两个 KB 各行，documents 各一行
    kbs, docs = _load_state()
    assert len(kbs) == 2
    assert len(docs) == 2
    # 两个 KB 行的文件级字段均为 None（去双写）
    for kb in kbs:
        assert kb["file_size"] is None
        assert kb["content_text"] is None
        assert kb["storage_key"] is None
    # 两个 document 行各自承载文件级字段
    for doc in docs:
        assert doc["file_size"] is not None and doc["file_size"] > 0
        assert doc["content_text"] is not None

    # 4. 同库追加相同文件仍被拒（同库判重仍在）
    resp_dup = integration_client.post(
        f"/api/knowledgebase/{kb_a_id}/documents",
        files={"file": ("shared-copy.txt", payload, "text/plain")},
    )
    assert resp_dup.json()["code"] != 200
