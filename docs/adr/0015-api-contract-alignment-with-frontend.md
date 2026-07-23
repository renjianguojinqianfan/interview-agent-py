# 复用前端的 API 契约对齐（裸数组 / 路径前缀 / 字段 / 流式格式 / 供应商标识）

ADR-0001 定「复用 Java 前端、Python API 与 Java 严格兼容」，ADR-0014 将前端并入 Python 单仓。逐页浏览器冒烟发现：除已修的语音 WS 外，多个非语音端点仍偏离 Java + 前端契约（分页对象 vs 裸数组、路径前缀不符、DTO 字段缺失、流式 SSE 格式不符、供应商标识类型不符），导致简历库 `/history`、面试中心 `/interview-hub`、知识库管理 `/knowledgebase`、问答助手 `/knowledgebase/chat`、设置 `/settings` 等页面崩溃或功能不可用。

我们决定：**以 Java Controller + 前端 TypeScript 类型为权威契约，逐模块改 Python 对齐，前端零改动。**

- **裸数组形状**：`GET /api/resumes`、`/api/interview/sessions`、`/api/knowledgebase/list`、`/api/rag-chat/sessions` 由 Python 的分页对象（`{items,total,page,size}`）改回裸数组 `Result<List<...>>`——前端直接对 `data` 做 `.map()`/`.some()`，Java 亦返回裸列表。相应去掉 page/size（及 interview 的 status）query 参数。
- **简历统计端点与字段**：新增 `GET /api/resumes/statistics`（`ResumeStats{totalCount,totalInterviewCount,totalAccessCount}`）。Java 参考快照未含该端点，但复用的前端 `/history` 页在 `Promise.all` 中调用它、缺失则整页加载失败——按 ADR-0001「前端为权威契约」补齐（前端权威优先于 Java 快照）。简历列表项补 `interviewCount`（按 resumeId 分组统计），详情补 `interviews[]`（关联面试记录）。跨模块只读统计由简历应用服务注入面试仓储实现。
- **知识库前缀与元数据**：路由前缀 `/api/knowledge-bases` 改为 `/api/knowledgebase`；补齐前端实际调用的 list（排序+状态过滤）/stats/categories/category/search/download/updateCategory 端点；`KnowledgeBaseListItemDTO` 字段对齐 Java（name/category/originalFilename/contentType/lastAccessedAt/accessCount/questionCount/... ）。`knowledge_bases` 表追加 name/category/access_count/question_count/last_accessed_at 列（追加式迁移 `alembic/versions/011_knowledge_base_metadata.py`，ADR-0002；last_accessed_at 建为 timestamptz，ADR-0013）。统计 totalQuestionCount 以 RAG 用户消息数计（对齐 Java，多知识库提问只算一次）。
- **RAG 前缀 / 形状 / 流式格式**：前缀 `/api/rag/sessions` 改为 `/api/rag-chat/sessions`；路径参数用数字主键 id；列表裸数组含 messageCount/knowledgeBaseNames/isPinned；详情含 knowledgeBases[] 且消息字段用 `type`（非 `role`）；置顶由 POST 改 PUT；新增 PUT title；流式端点由 `/query/stream` 改为 `/messages/stream`，其 SSE 由 JSON 包裹（`{"delta"}`/`{"sources"}`/`[DONE]`）改为**纯文本 data 帧**（换行转义），对齐 Java `ServerSentEvent<String>` 与前端 `parseMode:'event'` 直接拼接；错误用 `event: error` 帧。
- **LLM 供应商标识**：provider 对外标识由自增 int 改为字符串 id（= provider_name）；CRUD/测试/默认设置均按名查找，默认设置对外以名解析、内部仍存 int 主键（边界映射，不做数据库迁移）。对齐 Java `String id` 与前端 `ProviderItem.id: string`。

**不变量**：前端零改动；每模块后端补齐对应契约测试；`make verify` 双栈全绿；对齐后各页面浏览器冒烟 0 致命 console error。前端声明但无页面调用的死端点（面试 `/sessions/{id}/report`；知识库 `/query`、`/query/stream`、`/{id}`、`/uncategorized`；RAG `/{id}/knowledge-bases`；简历 `/health`）不实现，聚焦页面可用。

**后续修复（终局迁移审查）**：审查发现的功能性契约缺口已按前端权威修复——语音评估扁平 `answers[]`/`totalQuestions`/`evaluateError`、`GET /interview/sessions/{id}/details`、语音会话列表 `createdAt`/`actualDuration`/`messageCount`/`evaluateError`、文字面试创建 `forceCreate`/`resumeText`、创建请求 `llmProvider`（字符串供应商名，按名解析）。上述死端点仍不实现（前端无页面调用）。

**Considered Options**：
- 改前端迁就后端——**否**：违背 ADR-0001「前端为权威契约」，且分歧面广、回归风险高。
- 知识库缺失字段用默认值兜底、不加列——**否**：分类筛选/计数将非功能性；经与用户确认选定完整对齐 + 追加式迁移。
- 保留供应商 int id、仅改前端 create/默认设置——**否**：违背 ADR-0001，前端与 Java 均以字符串 id 为标识。
