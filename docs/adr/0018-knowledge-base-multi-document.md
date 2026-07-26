# ADR-0018: 知识库多文档模型（expand 阶段）

## 状态

已接受（2026-07-26，issue #52）

## 背景

`knowledge_bases` 表自 migration 005 起将文件级字段（`file_hash` 全局唯一、
`storage_key`、`content_text`、`vector_status` 等）内联在知识库行上，即"一库 = 一文件"。
向同一知识库再传文件没有入口，语义上等价于覆盖；向量归属信息存 JSONB
`metadata->>'kb_id'`，检索是无索引文本比较 + HNSW 后过滤，规模化后召回塌缩。

## 决策

按 expand-contract 分步演进，本 ADR 覆盖 expand 阶段：

1. **新表 `knowledge_base_documents`**（migration 013）：承接文件级字段
   （file_hash/original_filename/file_size/content_type/storage_key/storage_url/
   content_text/chunk_count/vector_status/vector_error/vector_job_id/uploaded_at/
   vectorized_at），FK `knowledge_base_id` ON DELETE CASCADE。文件去重收窄为
   `(knowledge_base_id, file_hash)` 复合唯一——同库去重、跨库允许。
2. **存量搬迁**：迁移内为每个既有 `knowledge_bases` 行幂等生成一条 document
   （同事务、`WHERE NOT EXISTS` 防重跑）。`knowledge_bases` 旧列全部保留不动，
   旧接口行为不变（上传新库 = 建库 + 一个文档，KB 行文件字段继续回写）。
3. **向量归属实体列**：`vector_store` 加 `knowledge_base_id`/`document_id`
   BIGINT 列 + `(knowledge_base_id, document_id)` btree 复合索引；存量按
   `metadata->>'kb_id'` 回填。检索 SQL 从 JSONB 后过滤改为列预过滤；
   删除按 document_id/knowledge_base_id 走索引，且仅删正式行
   （pending 行以 `metadata ? 'kb_vector_job_id'` 区分，两阶段提交协议不变）。
4. **向量化任务按文档粒度**：Stream payload 增加可选 `documentId`；缺省时按
   knowledge_base 粒度处理（兼容存量队列消息与整库重向量化）。文档级
   `vector_status` 落 document 行，KB 级 `vector_status` 为聚合视图
   （任一 FAILED→FAILED；存在 PENDING/PROCESSING→PROCESSING；全 COMPLETED→COMPLETED），
   `chunk_count` 为文档求和，旧字段继续写保证旧前端/统计兼容。
5. **API**：新增 `POST /api/knowledgebase/{id}/documents`（追加文档）、
   `GET /api/knowledgebase/{id}/documents`（文档列表）、
   `DELETE /api/knowledgebase/{id}/documents/{documentId}`（删文档并清理其向量）。

contract 阶段（后续独立工单）：待旧读路径全部切换到 documents 后，
移除 `knowledge_bases` 上的文件级列与全局 `file_hash` 唯一约束。

## 后果

- 一个知识库可聚合多份文档，上传第二个文件不再覆盖第一个；检索在整库范围命中。
- 向量检索由 btree 预过滤 + HNSW 替代 JSONB 全表文本比较，支撑文档规模增长。
- 过渡期内文件级数据双写（KB 首文档行 + document 行），属 expand 阶段刻意冗余，
  由 contract 阶段收敛；`kb_content_hash`（题库快照哈希，ADR-0017）语义暂不变，
  仍指 KB 首文档内容哈希。
- 迁移 013 可完整 downgrade（删索引/列/表），不触碰既有行。
