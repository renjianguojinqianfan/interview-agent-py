# 手写 pgvector CRUD，不用 LangChain PGVector

Java 的 VectorRepository 在 Spring AI PgVectorStore 之上有大量自定义 SQL：按知识库 ID 批量删除、按任务 ID 删除临时向量、临时向量提升为正式数据（`jsonb_set` 两阶段提交 pending -> promote）。我们决定手写 pgvector + SQLAlchemy CRUD，不用 LangChain PGVector。PGVector 抽象层不直接支持两阶段提交等自定义 `jsonb_set` 操作，用了反而多一层绕路。这也消除了 `langchain-postgres` 依赖需求。

**Considered Options**: LangChain PGVector / 手写 CRUD（选定）。PGVector 的自定义 SQL 需绕过抽象层，手写更直接。
