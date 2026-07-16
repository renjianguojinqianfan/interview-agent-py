# Java -> Python 迁移计划

> 源项目：Java/Spring Boot 面试 Agent（196 个 Java 文件，6 大业务模块）
> 目标项目：interview-agent-py（Python/FastAPI + LangGraph）
> 生成日期：2026-07-14
> 技术规格来源：`interview-agent-java/notes/` 00-05 文档 + `java-reference/` 源代码

---

## 已确认的技术决策

| 编号 | 决策点 | 选定方案 | 说明 |
|------|--------|---------|------|
| D1 | DDD 严格程度 | **务实 DDD（方案B）** | domain 层定义仓储接口（Protocol/ABC），infrastructure 层 SQLAlchemy 模型同时充当领域实体，application 层直接操作 ORM 模型 |
| D2 | 异步任务框架 | **redis.asyncio Stream 原生（方案B）** | 直接用 `XREADGROUP`/`XADD`/`XAUTOCLAIM`，完全复刻 Java Consumer Group 机制，不依赖额外框架 |
| D3 | LangGraph 使用深度 | **选择性使用（方案B）** | 仅统一评估子图和语音管线用 LangGraph StateGraph，其余用普通 async 函数 |
| D4 | 文档解析方案 | **unstructured 通用（方案A）** | 统一用 `unstructured` 库解析所有格式（PDF/DOCX/TXT/MD） |
| D5 | PDF 导出方案 | **WeasyPrint（方案A）** | HTML/CSS 模板生成 PDF，排版灵活 |
| D6 | 数据库迁移策略 | **Alembic（方案A）** | 版本化管理 schema 变更 |

---

## 一、现状分析

### 1.1 Java 参考项目（196 个 Java 文件）

| 维度 | 规模 |
|------|------|
| 业务模块 | 6 个（模拟面试、面试日程、知识库+RAG、LLM供应商、简历管理、语音面试） |
| Controller | 8 个，76 个 HTTP 接口 + 1 个 WebSocket 端点 |
| Entity | 11 个数据库表 |
| Service | 29+ 个 |
| 异步任务 | 4 套 Redis Stream Consumer/Producer |
| 资源文件 | 14 个 Prompt 模板(.st)、10 个技能目录、Lua 限流脚本、中文字体、开场问题配置 |
| 复杂度峰值 | 语音面试 WebSocket（ASR↔LLM↔TTS 三路流式管线）★★★★★ |

架构为经典 Spring MVC 三层：`Controller -> Service -> Repository`，公共能力在 `common/`（AI 调用、异步模板、评估、限流、异常），技术基础设施在 `infrastructure/`（文件、导出、Redis、MapStruct 映射）。

各模块文件分布：

| 模块 | 文件数 | 子目录数 | Controller | Entity | Repository | Service |
|------|--------|---------|------------|--------|------------|---------|
| interviewschedule | 11 | 3 | 1 | 1 | 1 | 3 |
| knowledgebase | 27 | 4 | 2 | 3 | 4 | 10 |
| resume | 16 | 4 | 1 | 2 | 2 | 7 |
| voiceinterview | 27 | 8 | 1 | 3 | 3 | 6 |
| llmprovider | 17 | 5 | 1 | 2 | 2 | 3 |
| infrastructure | 14 | 4 | - | - | - | (混合) |
| common | 38 | 10 | - | - | - | (混合) |
| **合计** | **~150** | - | **6** | **11** | **12** | **29+** |

### 1.2 Python 项目现状（几乎空白）

> **进度注记**：本节为迁移前快照。阶段 0-3（项目骨架 / AI 基础设施 / 异步任务+文件 / 简历模块）已完成，下方"待实现"列已不反映当前状态，仅作历史对照。当前进度详见 `docs/agents/review-plan.md` 的 Review 日历。

| 已就绪 | 待实现 |
|--------|--------|
| `pyproject.toml` 全部依赖已定义（FastAPI/LangGraph/SQLAlchemy/pgvector/redis/aioboto3/unstructured/weasyprint/slowapi 等） | 无任何业务代码 |
| `docker-compose.yml` 三件套就绪（PostgreSQL+pgvector / Redis / MinIO） | 无数据库模型 |
| `AGENTS.md` 定义 DDD 分层规范（api->application->domain<-infrastructure） | 无 API 路由 |
| `Makefile` 质量门禁（test+typecheck+lint） | 无配置管理 |
| `check_services.py` 基础设施连通性测试 | 无 Prompt 模板 |
| `README.md` 环境变量文档 | 无技能配置 |
| `app/main.py` 仅 8 行 Hello World | 无异步任务框架 |

**结论**：Python 端基础设施脚手架已搭好（依赖、Docker、规范），但业务代码从零开始。

---

## 二、目标架构

遵循 `AGENTS.md` 定义的分层架构（依赖方向：api -> application -> domain，infrastructure 实现 domain 定义的接口）。按模块复杂度分层：简单 CRUD 模块（供应商、日程）可不经过 domain 层；复杂业务逻辑（评估算法、出题策略、RAG 检索、语音阶段切换）必须隔离到 `domain/services/` 作为纯 Python 函数/类，接收 dataclass、返回 dataclass，不依赖任何框架。SQLAlchemy 模型留 `infrastructure/db/models/`，application 层负责 Model↔dataclass 转换。

```
app/
├── main.py                      # FastAPI 应用入口 + 中间件注册
├── config/                      # 配置管理（pydantic-settings）
│   ├── settings.py              # 全局配置（对应 application.yml）
│   ├── ai.py                    # AI/LLM 供应商配置
│   ├── storage.py               # S3/MinIO 存储配置
│   ├── voice.py                 # 语音面试阶段配置
│   └── cors.py                  # CORS 配置
├── api/                         # API 路由层（仅路由、校验、委托）
│   ├── deps.py                  # FastAPI Depends 依赖注入
│   ├── responses.py             # Result[T] 统一响应模型
│   ├── errors.py                # re-export from domain/errors.py（渐进式兼容）
│   ├── exception_handlers.py    # 全局异常处理器
│   └── routers/                 # 8 个 APIRouter（对应 8 个 Controller）
│       ├── interview.py         # 模拟面试 + 技能管理（15 接口）
│       ├── schedule.py          # 面试日程（7 接口）
│       ├── knowledgebase.py     # 知识库文件管理（14 接口）
│       ├── rag_chat.py          # RAG 聊天会话（8 接口）
│       ├── llm_provider.py      # LLM/ASR/TTS 供应商（15 接口）
│       ├── resume.py            # 简历上传与分析（7 接口）
│       ├── voice_interview.py   # 语音面试 REST（10 接口）
│       └── voice_ws.py          # 语音面试 WebSocket
├── application/                 # 应用服务层（业务编排、事务边界）
│   ├── interview/               # 文字面试应用服务
│   ├── resume/                  # 简历应用服务
│   ├── knowledgebase/           # 知识库应用服务
│   ├── rag/                     # RAG 问答应用服务
│   ├── schedule/                # 日程应用服务
│   ├── llm_provider/            # 供应商应用服务
│   └── voice/                   # 语音面试应用服务
├── domain/                      # 领域层（纯 Python，零框架依赖）
│   ├── errors.py                # ErrorCode 枚举 + BusinessException
│   ├── enums.py                 # 状态枚举（SessionStatus/AsyncTaskStatus/...）
│   ├── services/                # 领域服务（复杂业务逻辑，接收/返回 dataclass）
│   │   ├── evaluation.py        # 统一评估算法（分批+汇总+降级）
│   │   ├── question_gen.py      # 出题策略 + 降级链
│   │   ├── rag_query.py         # RAG 检索策略
│   │   └── voice_phase.py       # 语音面试阶段切换规则
│   └── repositories/            # 仓储接口（Protocol，仅复杂模块需要时定义）
├── infrastructure/              # 基础设施层（仓储实现 + 外部服务适配器）
│   ├── db/                      # SQLAlchemy 数据库层
│   │   ├── base.py              # Declarative Base + 公共 Mixin
│   │   ├── session.py           # 异步 Engine + SessionFactory
│   │   ├── models/              # SQLAlchemy ORM 模型
│   │   └── repositories/        # 仓储实现类（实现 domain 定义的 Protocol）
│   ├── redis/                   # Redis 服务
│   │   ├── client.py            # redis.asyncio 连接池
│   │   ├── session_cache.py     # 面试会话缓存
│   │   └── rate_limit.lua       # 限流 Lua 脚本（从 Java 迁移）
│   ├── storage/                 # S3/MinIO 文件存储
│   │   ├── s3.py                # aioboto3 文件上传/下载/删除
│   │   └── hash.py              # SHA-256 文件哈希
│   ├── ai/                      # LLM 调用基础设施
│   │   ├── llm_registry.py      # 多供应商 LLM 管理
│   │   ├── provider_snapshot.py # ProviderSnapshot + looks_like_chat_model（纯数据）
│   │   ├── structured_output.py # 结构化输出调用
│   │   ├── prompt_sanitizer.py  # Prompt 注入防御
│   │   ├── prompt_constants.py  # 安全指令常量
│   │   ├── encryption.py        # API Key 加密
│   │   ├── embeddings.py        # Embedding 模型管理
│   │   └── prompt_loader.py     # Prompt 模板加载（aiofiles 异步）
│   ├── parsing/                 # 文档解析
│   │   ├── parser.py            # unstructured 通用解析
│   │   ├── content_type.py      # 文件类型检测
│   │   └── text_cleaner.py      # 文本清洗
│   ├── export/                  # PDF 导出
│   │   └── pdf.py               # WeasyPrint HTML->PDF
│   ├── vector/                  # 向量数据库
│   │   └── repository.py        # pgvector CRUD + 两阶段提交
│   ├── tasks/                   # 异步任务（redis.asyncio Stream 原生）
│   │   ├── base_consumer.py     # 抽象消费者
│   │   ├── base_producer.py     # 抽象生产者
│   │   ├── resume_analyze.py    # 简历分析任务
│   │   ├── interview_evaluate.py# 面试评估任务
│   │   ├── kb_vectorize.py      # 知识库向量化任务
│   │   └── voice_evaluate.py    # 语音面试评估任务
│   ├── voice/                   # 语音服务适配器
│   │   ├── asr.py               # Qwen ASR WebSocket 客户端
│   │   ├── tts.py               # Qwen TTS WebSocket 客户端
│   │   └── audio_utils.py       # PCM->WAV 转换等音频工具
│   └── scheduler/               # 定时任务（APScheduler）
├── graphs/                      # LangGraph 状态图（仅评估子图 + 语音管线）
│   ├── evaluation.py            # 统一评估子图
│   └── voice_pipeline.py        # 语音管线状态图
├── prompts/                     # Prompt 模板（从 Java .st 迁移）
├── skills/                      # 技能配置（从 Java skills/ 迁移）
└── static/                      # 静态资源
    └── fonts/                   # 中文字体（ZhuqueFangsong-Regular.ttf）
```

---
## 三、组件映射表

### 3.1 公共层（common/ -> 多处）

| Java 组件 | Python 目标 | 说明 |
|-----------|------------|------|
| `LlmProviderRegistry` | `infrastructure/ai/llm_registry.py` | LangChain `ChatOpenAI` 工厂 + `base_url` 适配，三种客户端类型（plain/voice/default） |
| `StructuredOutputInvoker` | `infrastructure/ai/structured_output.py` | `with_structured_output()` + `tenacity` 重试（2 次）+ `json-repair` 修复 |
| `PromptSanitizer` | `infrastructure/ai/prompt_sanitizer.py` | `re` 正则完全等价 + UUID 动态分隔符 |
| `PromptSecurityConstants` | `infrastructure/ai/prompt_constants.py` | 安全指令常量 |
| `UnifiedEvaluationService` | `domain/services/evaluation.py` + `graphs/evaluation.py` | 分批评估+二次汇总，文字/语音共用，LangGraph 子图 |
| `AbstractStreamConsumer/Producer` | `infrastructure/tasks/base_consumer.py` + `base_producer.py` | redis.asyncio Stream 原生实现（XREADGROUP/XADD/XAUTOCLAIM） |
| `RateLimitAspect` + `@RateLimit` | `slowapi` 装饰器 | 滑动窗口限流 |
| `GlobalExceptionHandler` | `api/exception_handlers.py` | FastAPI `@app.exception_handler`，统一 HTTP 200 |
| `ErrorCode` / `BusinessException` | `api/errors.py` | Python Enum + Exception 类 |
| `Result<T>` | `api/responses.py` | Pydantic 泛型模型 |
| `TransactionalExecutor` | SQLAlchemy `async with session.begin()` | Python 无 AOP 代理问题 |
| `ApiPathResolver` | `infrastructure/ai/llm_registry.py` 内部 | `openai` SDK `base_url` + `httpx` 超时配置 |

### 3.2 基础设施层（infrastructure/ -> infrastructure/）

| Java 组件 | Python 目标 | 技术 |
|-----------|------------|------|
| `FileStorageService` | `infrastructure/storage/s3.py` | `aioboto3`（异步 S3） |
| `DocumentParseService` | `infrastructure/parsing/parser.py` | `unstructured`（通用解析） |
| `ContentTypeDetectionService` | `infrastructure/parsing/content_type.py` | `filetype`（纯 Python，替代 python-magic。详见 ADR-0009） |
| `FileHashService` | `infrastructure/storage/hash.py` | `hashlib.sha256()` |
| `FileValidationService` | `api/deps.py` + Pydantic 验证器 | FastAPI `UploadFile` |
| `TextCleaningService` | `infrastructure/parsing/text_cleaner.py` | `re` 预编译正则 |
| `PdfExportService` | `infrastructure/export/pdf.py` | `WeasyPrint`（HTML->PDF） |
| `VectorRepository` | `infrastructure/vector/repository.py` | `pgvector` + SQLAlchemy 手写 CRUD（不用 LangChain PGVector。详见 ADR-0006） |
| `InterviewSessionCache` | `infrastructure/redis/session_cache.py` | `redis.asyncio` + Pydantic 序列化 |
| `RedisService` | `infrastructure/redis/client.py` | `redis.asyncio`（缓存/锁/Stream） |
| MapStruct Mappers (4个) | `infrastructure/mappers/` 或直接 Pydantic 转换 | 手写映射函数 |

### 3.3 数据库模型（11+ 个 Entity -> SQLAlchemy ORM）

| Java Entity | 表名 | Python ORM 模型 | 关键状态字段 |
|-------------|------|----------------|-------------|
| `InterviewSessionEntity` | interview_sessions | `InterviewSession` | status, evaluateStatus |
| `InterviewAnswerEntity` | interview_answers | `InterviewAnswer` | - |
| `InterviewScheduleEntity` | interview_schedule | `InterviewSchedule` | status(InterviewStatus) |
| `KnowledgeBaseEntity` | knowledge_bases | `KnowledgeBase` | vectorStatus(VectorStatus) |
| `RagChatSessionEntity` | rag_chat_sessions | `RagChatSession` | status |
| `RagChatMessageEntity` | rag_chat_messages | `RagChatMessage` | - |
| `LlmProviderEntity` | llm_provider_config | `LlmProvider` | - |
| `LlmGlobalSettingEntity` | llm_global_setting | `LlmGlobalSetting` | - |
| `ResumeEntity` | resumes | `Resume` | analyzeStatus(AsyncTaskStatus) |
| `ResumeAnalysisEntity` | resume_analyses | `ResumeAnalysis` | - |
| `VoiceInterviewSessionEntity` | voice_interview_sessions | `VoiceInterviewSession` | status, currentPhase, evaluateStatus |
| `VoiceInterviewMessageEntity` | voice_interview_messages | `VoiceInterviewMessage` | - |
| `VoiceInterviewEvaluationEntity` | voice_interview_evaluations | `VoiceInterviewEvaluation` | - |
| (Spring AI 自动管理) | vector_store | `VectorStore` | pgvector 向量表 |

### 3.4 资源文件迁移

| Java 资源 | Python 目标 | 处理方式 |
|-----------|------------|---------|
| 14 个 `.st` Prompt 模板 | `app/prompts/*.st`（或 `.j2`） | 直接迁移，StringTemplate 语法与 Jinja2 兼容性需逐个核对 |
| 10 个技能目录(`skills/`) | `app/skills/` | 直接迁移 SKILL.md + skill.meta.yml |
| `voice-interview-opening.yml` | `app/skills/opening.yml` 或合并到 config | 开场问题配置 |
| `rate_limit_single.lua` | `infrastructure/redis/rate_limit.lua` | Lua 脚本可直接复用（slowapi 用 Redis 时） |
| `ZhuqueFangsong-Regular.ttf` | `app/static/fonts/` | 中文字体，PDF 导出用 |
| `application.yml` | `app/config/settings.py` + `.env` | pydantic-settings，环境变量驱动 |

### 3.5 状态机映射

| Java 状态机 | 状态数 | Python 枚举 | LangGraph 映射 |
|-------------|-------|------------|---------------|
| 文字面试 SessionStatus | 4 | `SessionStatus` | 主流程条件边（CREATED/IN_PROGRESS/COMPLETED/EVALUATED） |
| 异步任务 AsyncTaskStatus | 4 | `AsyncTaskStatus` | Stream 消费者状态机（PENDING/PROCESSING/COMPLETED/FAILED） |
| 面试日程 InterviewStatus | 4 | `InterviewStatus` | 简单状态机 + APScheduler 定时过期 |
| 语音面试 SessionStatus | 4 | `VoiceSessionStatus` | WebSocket 事件驱动 + 定时检查 |
| 语音面试 InterviewPhase | 5 | `InterviewPhase` | LangGraph 语音管线条件边 |
| 知识库 VectorStatus | 4 | `VectorStatus` | Stream 消费者状态机 |
| 简历 analyzeStatus | 4 | (复用 AsyncTaskStatus) | Stream 消费者状态机 |
| RAG 聊天 SessionStatus | 2 | `RagSessionStatus` | ACTIVE/ARCHIVED |

---
## 四、分阶段迁移计划

### 阶段 0：项目骨架（预计 2-3 天）

**目标**：搭好可运行的最小骨架，所有后续模块在此上构建。

| # | 任务 | 产出 |
|---|------|------|
| 0.1 | 配置管理（静态） | `app/config/settings.py`（pydantic-settings，对应 application.yml 静态配置项：DB/Redis/S3/CORS/语音参数/限流参数等）+ `.env.example` |
| 0.1b | 配置管理（动态） | `app/config/` LLM Provider 动态配置：数据库 + 内存缓存（去掉 Java 的 YAML 中间层），启动时种子默认 dashscope provider（API Key 空）。详见 ADR-0004 |
| 0.2 | 数据库基础 | `infrastructure/db/session.py`（async engine + session factory）+ Alembic 迁移初始化 |
| 0.3 | Redis 客户端 | `infrastructure/redis/client.py`（redis.asyncio 连接池） |
| 0.4 | 统一响应 + 异常 | `api/responses.py`（Result[T]）+ `api/errors.py`（ErrorCode 枚举 50+ 错误码 + BusinessException）+ `api/exception_handlers.py`（全局异常处理，统一 HTTP 200） |
| 0.5 | CORS + 中间件 | `main.py` 注册 CORSMiddleware + slowapi Limiter |
| 0.6 | 健康检查 | `/health` 端点 + OpenAPI 文档配置 |
| 0.7 | 依赖注入框架 | `api/deps.py`（DB session、Redis、S3、LLM Registry 的 Depends provider） |

**验收**：`uv run uvicorn app.main:app` 启动成功，`/docs` 可访问，`/health` 返回 200，`make verify` 通过。

---

### 阶段 1：公共 AI 基础设施（预计 3-4 天）

**目标**：搭建所有模块共用的 AI 调用基础设施，这是后续每个业务模块的前置依赖。

| # | 任务 | 对应 Java 组件 | 说明 |
|---|------|---------------|------|
| 1.1 | LLM 供应商注册中心 | `LlmProviderRegistry` | `infrastructure/ai/llm_registry.py`：LangChain `ChatOpenAI` 工厂，三种客户端（plain/default/voice），DB > YAML > 默认三级配置 |
| 1.2 | 结构化输出调用器 | `StructuredOutputInvoker` | `infrastructure/ai/structured_output.py`：`with_structured_output()` + `tenacity` 重试（2 次）+ `json-repair` 修复 |
| 1.3 | Prompt 注入防御 | `PromptSanitizer` + `PromptSecurityConstants` | `infrastructure/ai/prompt_sanitizer.py`：4 类正则清洗 + UUID 动态分隔符 |
| 1.4 | API Key 加密 | `ApiKeyEncryptionService` | `infrastructure/ai/encryption.py`：`cryptography` 库 AES-GCM |
| 1.5 | Embedding 管理 | `LlmEmbeddingConfig` | `infrastructure/ai/embeddings.py`：LangChain `OpenAIEmbeddings`，维度 1024 |
| 1.6 | 统一评估服务 | `UnifiedEvaluationService` | `domain/services/evaluation.py`：分批评估 + 二次汇总 + 两级降级（文字/语音共用），LangGraph 子图 |
| 1.7 | Prompt 模板迁移 | 14 个 `.st` 文件 | `app/prompts/`：逐个迁移并验证语法兼容性 |

**验收**：单元测试覆盖 LLM 调用（mock）、结构化输出解析与重试、Prompt 清洗规则、评估算法（mock LLM 返回）。

---

### 阶段 2：异步任务框架 + 文件基础设施（预计 3-4 天）

**目标**：搭建 4 套异步任务共用的框架 + 文件处理管线。

| # | 任务 | 对应 Java 组件 | 说明 |
|---|------|---------------|------|
| 2.1 | 异步任务基类 | `AbstractStreamConsumer/Producer` | `infrastructure/tasks/base_*.py`：redis.asyncio Stream + 消费者组 + Pending 回收(5min) + 重试(3次) + 幂等(shouldSkip) + 状态机 |
| 2.2 | S3 文件存储 | `FileStorageService` | `infrastructure/storage/s3.py`：aioboto3 上传/下载/删除，存储键格式 `{prefix}/{yyyy/MM/dd}/{uuid}_{filename}` |
| 2.3 | 文档解析 | `DocumentParseService` | `infrastructure/parsing/parser.py`：unstructured 通用解析（PDF/DOCX/TXT/MD） |
| 2.4 | 文件类型检测 | `ContentTypeDetectionService` | `infrastructure/parsing/content_type.py`：`filetype` 魔数检测（纯 Python，无 C 依赖。详见 ADR-0009） |
| 2.5 | 文件哈希 + 校验 | `FileHashService` + `FileValidationService` | SHA-256 去重 + 大小/类型白名单校验 |
| 2.6 | 文本清洗 | `TextCleaningService` | `infrastructure/parsing/text_cleaner.py`：语义去噪 + 格式规范化 |
| 2.7 | 向量仓储 | `VectorRepository` | `infrastructure/vector/repository.py`：pgvector CRUD + 两阶段提交(pending->promote) |

**验收**：能上传文件到 MinIO、计算哈希、解析文本、写入 pgvector。

---
### 阶段 3：简历模块（P1，预计 4-5 天）

**目标**：完成第一个完整业务闭环（上传->解析->去重->异步分析->评分->PDF 导出）。

| # | 任务 | 接口数 | 说明 |
|---|------|--------|------|
| 3.1 | 数据模型 | - | `Resume` + `ResumeAnalysis` ORM 模型 + Alembic 迁移 |
| 3.2 | 领域层 | - | `domain/entities/resume.py`（analyzeStatus 状态机）+ 仓储接口 |
| 3.3 | 应用服务 | - | `application/resume/`：UploadService（上传->解析->去重->入队）、GradingService（LLM 评分+降级）、PersistenceService |
| 3.4 | 异步任务 | - | `infrastructure/tasks/resume_analyze.py`：消费 resume:analyze:stream |
| 3.5 | API 路由 | 7 | `api/routers/resume.py`：upload/list/detail/export/delete/reanalyze/health |
| 3.6 | PDF 导出 | - | `infrastructure/export/pdf.py`：WeasyPrint 简历分析报告 |
| 3.7 | 限流 | - | upload: GLOBAL=5/s+IP=5/s，reanalyze: GLOBAL=2/s+IP=2/s |

**验收**：上传 PDF 简历 -> 异步分析 -> 查看评分详情 -> 导出 PDF 报告，全流程跑通。

---

### 阶段 4：文字面试模块（P0 核心，预计 6-8 天）

**目标**：完成核心面试闭环（创建会话->出题->答题->评估->报告），这是平台最核心的业务流程。

| # | 任务 | 接口数 | 说明 |
|---|------|--------|------|
| 4.1 | 数据模型 | - | `InterviewSession` + `InterviewAnswer` ORM + Alembic 迁移 |
| 4.2 | 领域层 | - | `domain/entities/interview.py`（SessionStatus 状态机：CREATED->IN_PROGRESS->COMPLETED->EVALUATED）+ 出题领域服务 + 评估领域服务 |
| 4.3 | 出题服务 | - | `domain/services/question_gen.py`：有简历->并行出题（asyncio.gather 简历题60%+方向题40%）+ 降级链；无简历->方向出题。追问机制(MAX_FOLLOW_UP=2) |
| 4.4 | 会话缓存 | - | `infrastructure/redis/session_cache.py`：双写策略（先DB后Redis）+ resume->session 映射 + TTL 24h |
| 4.5 | 应用服务 | - | `application/interview/`：SessionService（生命周期）、QuestionService、EvaluationService、PersistenceService |
| 4.6 | 异步评估任务 | - | `infrastructure/tasks/interview_evaluate.py`：消费 interview:evaluate:stream，调用 UnifiedEvaluationService |
| 4.7 | 技能管理 | - | `domain/services/skill.py` + 技能配置（skills/ 目录迁移）+ JD 解析 |
| 4.8 | API 路由 | 15 | `api/routers/interview.py`：sessions CRUD + answers + report + export + skills + parse-jd |
| 4.9 | 限流 | - | create: GLOBAL=5/s+IP=5/s，answers: GLOBAL=10/s，parse-jd: IP=5/s |
| 4.10 | PDF 导出 | - | 面试报告 PDF（评分颜色 + 逐题详情） |

**验收**：创建面试 -> 答题 -> 提前交卷/答完 -> 异步评估 -> 查看报告 -> 导出 PDF，含断线续答、并行出题降级。

---
### 阶段 5：知识库 + RAG 模块（P1，预计 5-6 天）

**目标**：完成知识库文件管理和 RAG 问答（含 SSE 流式）。

| # | 任务 | 接口数 | 说明 |
|---|------|--------|------|
| 5.1 | 数据模型 | - | `KnowledgeBase` + `RagChatSession` + `RagChatMessage` + `VectorStore`(pgvector) ORM |
| 5.2 | 领域层 | - | `domain/entities/knowledgebase.py`（VectorStatus 状态机）+ RAG 检索策略领域服务 |
| 5.3 | 知识库上传 | - | `application/knowledgebase/`：UploadService（上传->解析->去重->入队向量化） |
| 5.4 | 向量化任务 | - | `infrastructure/tasks/kb_vectorize.py`：文档分块 + Embedding + 写入 pgvector，两阶段提交(pending->promote) |
| 5.5 | RAG 查询 | - | `domain/services/rag_query.py`：Query Rewrite(可选) + 动态 topK/minScore + 多候选检索 + 探测窗口归一化(120字符) |
| 5.6 | RAG 聊天会话 | - | `application/rag/`：SessionService + 流式 SSE 消息（prepareStreamMessage -> 流式 -> completeStreamMessage） |
| 5.7 | API 路由 | 22 | `knowledgebase.py`(14) + `rag_chat.py`(8) |
| 5.8 | 限流 | - | query: GLOBAL=10/s+IP=10/s，query/stream: GLOBAL=5/s+IP=5/s，upload: GLOBAL=3/s+IP=3/s，revectorize: GLOBAL=2/s+IP=2/s |

**验收**：上传知识库文件 -> 自动向量化 -> 创建 RAG 聊天会话 -> 流式问答，含无结果检测和归一化。

---

### 阶段 6：LLM 供应商 + 面试日程（P2，预计 3-4 天）

**目标**：完成配置管理类模块。

| # | 任务 | 接口数 | 说明 |
|---|------|--------|------|
| 6.1 | LLM 供应商 | 15 | `LlmProvider` + `LlmGlobalSetting` ORM + CRUD + 测试连通性 + 默认供应商 + ASR/TTS 配置 + 热更新(reload) |
| 6.2 | API Key 加密 | - | `cryptography` AES-GCM，对应 ApiKeyEncryptionService |
| 6.3 | 面试日程 | 7 | `InterviewSchedule` ORM + CRUD + 邀约文本解析(LLM) + 定时任务(APScheduler 每小时过期取消) |
| 6.4 | 限流 | - | Provider: 读=30/s 写=5/s 测试=10/s（均 GLOBAL） |

**验收**：可配置多 LLM 供应商、切换默认供应商、测试连通性；面试日程 CRUD + 解析 + 自动过期。

---
### 阶段 7：语音面试模块（P3，预计 8-12 天）

**目标**：实现最复杂的 WebSocket 实时语音面试。最后实现，因为依赖前面所有基础设施。

分三个子阶段：

#### 7A. REST 生命周期（2-3 天）

| # | 任务 | 说明 |
|---|------|------|
| 7A.1 | 数据模型 | `VoiceInterviewSession` + `VoiceInterviewMessage` + `VoiceInterviewEvaluation` ORM |
| 7A.2 | 领域层 | VoiceInterviewSessionStatus 状态机 + InterviewPhase 阶段流转 + 阶段配置(min/suggested/max duration + min/max questions) |
| 7A.3 | 应用服务 | SessionService（创建/结束/暂停/恢复）+ 事务后发送(afterCommit -> SQLAlchemy event) |
| 7A.4 | 异步评估任务 | `voice_evaluate.py`：消费 voice:evaluate:stream |
| 7A.5 | API 路由 | 10 个 REST 接口 |
| 7A.6 | 定时任务 | APScheduler：暂停超时检查(30s) + 僵尸会话清理(5min) |

#### 7B. WebSocket 实时管线（4-6 天）-- 全项目最复杂部分

| # | 任务 | 说明 |
|---|------|------|
| 7B.1 | WebSocket 端点 | `@router.websocket("/ws/voice-interview/{session_id}")`，消息协议（audio/control/subtitle/text/audio_chunk/error） |
| 7B.2 | ASR 服务 | `infrastructure/voice/asr.py`：Qwen3 Realtime ASR WebSocket 客户端，partial/final 结果 |
| 7B.3 | TTS 服务 | `infrastructure/voice/tts.py`：Qwen3 TTS Realtime WebSocket 客户端，PCM->WAV 转换(24kHz/16-bit/mono/44字节头) |
| 7B.4 | 语音 LLM 服务 | Dashscope 流式 LLM 调用（对应 DashscopeLlmService） |
| 7B.5 | 回声抑制 | AI 说话中 + 播放后 800ms 冷却期丢弃麦克风输入 |
| 7B.6 | 多段 STT 合并 | VAD 切段累积 mergeBuffer，debounce 提交(min_commit_chars=20, debounce=2500ms) |
| 7B.7 | 句子级并发 TTS | 检测完整句子即启动 TTS，maxConcurrent=3，timeout=8s，分块/合并两种模式 |
| 7B.8 | 阶段切换 | shouldTransitionToNextPhase 三规则（maxDuration 强制 / maxQuestions 建议 / suggestedDuration+minQuestions 建议） |
| 7B.9 | 开场问题 | 连接建立时按 skillId 匹配预设开场问题 + TTS 预合成 |
| 7B.10 | 暂停超时 | 4分30秒警告，5分钟自动暂停断开 |
| 7B.11 | ASR 重连 | 最多 2 次，每次延迟 10 秒 |

#### 7C. 语音评估 + 集成测试（2-3 天）

| # | 任务 | 说明 |
|---|------|------|
| 7C.1 | 语音评估 | 复用 UnifiedEvaluationService（QaRecord 适配）+ VoiceInterviewEvaluation 持久化 |
| 7C.2 | 消息回填 | fillLatestUnansweredQuestion（用户回答回填到最近 AI 消息） |
| 7C.3 | 端到端测试 | WebSocket 连接 -> 音频流 -> ASR -> LLM -> TTS -> 阶段切换 -> 结束 -> 评估 |

**验收**：前端 WebSocket 连接 -> 实时语音对话 -> 字幕显示 -> AI 语音回复 -> 阶段自动切换 -> 结束评估。

---

### 阶段 8：收尾与加固（预计 2-3 天）

| # | 任务 | 说明 |
|---|------|------|
| 8.1 | 全局限流完善 | slowapi 限流规则全量配置（对应 10 组限流接口），Lua 脚本迁移或 slowapi 内置算法 |
| 8.2 | IP 获取逻辑 | 依次尝试 X-Forwarded-For -> X-Real-IP -> Proxy-Client-IP -> remote_addr，用户 ID 从 header X-User-Id |
| 8.3 | 幂等性加固 | 文件 Hash 去重 + 状态机幂等（交卷/暂停/恢复/评估触发）+ 异步任务 shouldSkip + Provider 创建去重 |
| 8.4 | 定时任务汇总 | APScheduler 注册：日程过期取消(每小时) + 暂停超时检查(30s) + 僵尸会话清理(5min) |
| 8.5 | 错误码全量校验 | 50+ 错误码全部映射（见附录） |
| 8.6 | AI 异常细分 | 超时(7002)/握手失败(7001)/密钥无效(7004)/频率超限(7005)/其他(7003) 分别映射 |
| 8.7 | 集成测试 | 各模块端到端流程测试 + 异步任务测试 + WebSocket 测试 |
| 8.8 | Dockerfile | Python 应用容器化 |

---
## 五、关键技术挑战与方案

### 挑战 1：语音面试 WebSocket 三路流式管线（复杂度最高）

**Java 实现**：`TextWebSocketHandler` + 虚拟线程 + `ConcurrentWebSocketSessionDecorator`

**Python 方案**：FastAPI `@router.websocket` + `asyncio` 协程

```
WebSocket 收到 audio(Base64 PCM)
    |
    +- [回声抑制检查] AI说话中 or 800ms冷却 -> 丢弃
    |
    +- async: 发送到 ASR WebSocket (wss://dashscope.../realtime)
    |     +- partial -> 发送 subtitle(isFinal=false)
    |     +- final -> 累积到 mergeBuffer
    |
    +- [debounce 提交] 2500ms 静音 + min_commit_chars=20
    |     +- 合并 mergeBuffer
    |     +- async: 流式调用 LLM
    |     |     +- 每段 -> 发送 text(final=false)
    |     |     +- 检测完整句子 -> asyncio.create_task(TTS)  <- 句子级并发
    |     |           +- 并发限制: asyncio.Semaphore(3)
    |     |           +- 超时: asyncio.wait_for(8s)
    |     |           +- 完成 -> 发送 audio_chunk(index, isLast)
    |     +- LLM 完成 -> 发送 text(final=true) + 保存DB + 检查阶段切换
    |
    +- [定时检查] 30s 暂停超时 / 5min 自动暂停
```

**关键点**：
- ASR/TTS 各自是独立的 WebSocket 连接，需要 `asyncio` 同时管理 3 个 WebSocket（客户端-服务器、服务器-ASR、服务器-TTS）
- 句子级并发 TTS 用 `asyncio.Semaphore(3)` + `asyncio.wait_for(timeout=8)` 实现
- PCM->WAV 转换手动拼 44 字节头（24kHz/16-bit/mono）
- 回声抑制用时间戳标记 + 800ms 冷却窗口

---

### 挑战 2：UnifiedEvaluationService 分批评估 + 二次汇总

**Java 实现**：顺序分批 LLM 调用 + 合并 + 二次汇总 LLM 调用

**Python 方案**：`domain/services/evaluation.py` 纯函数 + LangGraph 子图

```
evaluate(chat_client, qa_records, resume_text, reference_context)
    |
    +- 1. 简历截断(>3000) + 参考基线截断(>6000)
    |
    +- 2. 分批评估（batch_size=8）
    |     +- asyncio.gather 并行各批 LLM 调用（Java 是顺序的，Python 可并行优化）
    |         每批 -> BatchReportDTO(overallScore, feedback, strengths, improvements, questionEvaluations)
    |         失败 -> None（后续零分兜底）
    |
    +- 3. 合并批次
    |     +- mergeQuestionEvaluations（缺失补零分）
    |     +- mergeOverallFeedback（拼接）
    |     +- mergeListItems（去重 + 限 8 条）
    |
    +- 4. 二次汇总 LLM 调用 -> SummaryDTO
    |     失败 -> 降级到批次聚合结果
    |
    +- 5. buildReport（逐题评估 + 分类平均分 + 总分=已答题平均分）
```

**优化点**：Java 分批是顺序执行，Python 可用 `asyncio.gather` 并行各批次，显著加速。

---

### 挑战 3：Redis Stream 异步任务框架

**Java 实现**：`AbstractStreamConsumer` 守护线程 + `XREADGROUP` + `XAUTOCLAIM` + ACK

**Python 方案**：redis.asyncio Stream 原生实现（D2 决策）

**核心机制保留**：
- 消费者组模式（XREADGROUP 阻塞读取，1s 超时）
- Pending 回收（XAUTOCLAIM idle>5min）
- 重试（最多 3 次，超过 markFailed）
- 幂等（shouldSkip 检查已完成则 ACK 丢弃）
- 状态机（PENDING -> PROCESSING -> COMPLETED/FAILED）
- Producer XADD maxLen=1000 裁剪

---

### 挑战 4：RAG 查询优化

**Java 实现**：Query Rewrite + 动态 topK + 多候选检索 + 探测窗口归一化

**Python 方案**：`domain/services/rag_query.py`

```
answerQuestionStream(knowledge_base_ids, question, history)
    |
    +- 1. 空查询防护
    +- 2. Query Rewrite（可选开关，失败回退原问题）
    +- 3. 动态参数：短(<=4字符) topK=20/minScore=0.18；中(<=12) topK=12；长 topK=8
    +- 4. 多候选检索：重写query + 原始query，任一命中即返回（asyncio.gather 并行）
    +- 5. 无命中 -> 固定无结果提示
    +- 6. 流式 LLM 调用（带历史上下文 + 防注入指令）
    +- 7. 探测窗口归一化：前 120 字符判断"无信息"模板 -> 替换为标准提示
```

---

### 挑战 5：并行出题降级链

**Java 实现**：`CompletableFuture` + 虚拟线程

**Python 方案**：`asyncio.gather` + `asyncio.wait`（return_when=FIRST_COMPLETED）

```
有简历：
    +- asyncio.gather(resume_questions, direction_questions)
    |     +- 简历题失败 -> 降级全方向题
    |     +- 方向题失败 -> 降级全简历题
    |     +- 两者都空 -> 默认模板题
    +- mergeQuestionBatches（重新编号）
```

---

### 挑战 6：事务后发送

**Java 实现**：`TransactionSynchronization.afterCommit()` 确保事务提交后才发 Redis Stream 消息

**Python 方案**：SQLAlchemy 事件监听或显式顺序控制

```python
# 方案A：SQLAlchemy after_commit 事件
@event.listens_for(session, "after_commit")
def after_commit(session):
    for task in session.info.get("pending_tasks", []):
        await producer.send(task)

# 方案B：显式顺序（✅ 已确认，详见 ADR-0008）
# 加降级：不在事务中时直接发送（与 Java 降级行为一致）
async def end_session(session_id):
    async with session.begin():
        session.update(status=COMPLETED, ...)
    # 事务提交后（离开 context manager）才发消息
    await producer.send_evaluate_task(session_id)
```

---
## 六、总工期与里程碑

| 阶段 | 内容 | 预计工期 | 累计 | 里程碑 |
|------|------|---------|------|--------|
| 0 | 项目骨架 | 2-3 天 | 3 天 | 可运行的空壳应用 |
| 1 | 公共 AI 基础设施 | 3-4 天 | 7 天 | LLM 可调用 |
| 2 | 异步任务 + 文件基础设施 | 3-4 天 | 11 天 | 文件可上传解析 |
| 3 | 简历模块 | 4-5 天 | 16 天 | **第一个完整业务闭环** |
| 4 | 文字面试模块 | 6-8 天 | 24 天 | **核心面试流程跑通** |
| 5 | 知识库 + RAG | 5-6 天 | 30 天 | RAG 问答可用 |
| 6 | LLM 供应商 + 日程 | 3-4 天 | 34 天 | 配置管理完整 |
| 7 | 语音面试 | 8-12 天 | 46 天 | **全功能完成** |
| 8 | 收尾加固 | 2-3 天 | 49 天 | 生产就绪 |

**总预计**：约 7-10 周（1-2 人全职）。

---

## 七、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 语音 WebSocket 管线过于复杂 | 阶段 7 可能延期 | 拆分为 7A/7B/7C 三个子阶段，7A 先交付 REST 生命周期，7B 是核心难点可单独攻坚 |
| unstructured 解析质量不如 Tika | 简历/知识库文本提取不完整 | 保留 pdfplumber/python-docx 作为后备方案 |
| LangGraph 学习成本 | 阶段 1/4 可能卡住 | 先用普通 asyncio 实现，评估子图稳定后再迁入 LangGraph |
| redis.asyncio Stream 语义实现复杂 | 异步任务幂等/重试机制不完整 | 完整复刻 Java AbstractStreamConsumer 的 Pending 回收 + shouldSkip + 状态机 |
| pgvector 两阶段提交复杂 | 向量化数据一致性风险 | 完整迁移 pending->promote 模式 + cleanup 补偿事务 |
| 中文字体在 WeasyPrint 中渲染 | PDF 导出乱码 | 迁移 ZhuqueFangsong-Regular.ttf，HTML CSS 中 @font-face 指定 |

---

## 附录 A：错误码全量表

### 成功码

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 200 | SUCCESS | 成功（`CommonConstants.StatusCode.SUCCESS = 200`，非 0） |

### 通用错误码

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 400 | BAD_REQUEST | 请求参数错误 |
| 401 | UNAUTHORIZED | 未授权 |
| 403 | FORBIDDEN | 禁止访问 |
| 404 | NOT_FOUND | 资源不存在 |
| 405 | METHOD_NOT_ALLOWED | 请求方法不支持 |
| 500 | INTERNAL_ERROR | 服务器内部错误 |

### 简历模块（2001-2008）

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 2001 | RESUME_NOT_FOUND | 简历不存在 |
| 2002 | RESUME_PARSE_FAILED | 简历解析失败 |
| 2003 | RESUME_UPLOAD_FAILED | 简历上传失败 |
| 2004 | RESUME_DUPLICATE | 简历已存在 |
| 2006 | RESUME_FILE_TYPE_NOT_SUPPORTED | 不支持的文件类型 |
| 2007 | RESUME_ANALYSIS_FAILED | 简历分析失败 |
| 2008 | RESUME_ANALYSIS_NOT_FOUND | 简历分析结果不存在 |

### 面试模块（3001-3008）

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 3001 | INTERVIEW_SESSION_NOT_FOUND | 面试会话不存在 |
| 3002 | INTERVIEW_SESSION_EXPIRED | 面试会话已过期 |
| 3003 | INTERVIEW_QUESTION_NOT_FOUND | 面试问题不存在 |
| 3004 | INTERVIEW_ALREADY_COMPLETED | 面试已完成 |
| 3005 | INTERVIEW_EVALUATION_FAILED | 面试评估失败 |
| 3006 | INTERVIEW_QUESTION_GENERATION_FAILED | 面试问题生成失败 |
| 3007 | INTERVIEW_NOT_COMPLETED | 面试尚未完成 |
| 3008 | INTERVIEW_ANSWER_SAVE_FAILED | 面试答案保存失败 |

### 存储模块（4001-4003）

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 4001 | STORAGE_UPLOAD_FAILED | 文件上传失败 |
| 4002 | STORAGE_DOWNLOAD_FAILED | 文件下载失败 |
| 4003 | STORAGE_DELETE_FAILED | 文件删除失败 |

### 导出模块（5001）

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 5001 | EXPORT_PDF_FAILED | PDF 导出失败 |

### 知识库模块（6001-6006）

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 6001 | KNOWLEDGE_BASE_NOT_FOUND | 知识库不存在 |
| 6002 | KNOWLEDGE_BASE_PARSE_FAILED | 知识库文件解析失败 |
| 6004 | KNOWLEDGE_BASE_QUERY_FAILED | 知识库查询失败 |
| 6005 | KNOWLEDGE_BASE_DELETE_FAILED | 知识库删除失败 |
| 6006 | KNOWLEDGE_BASE_VECTORIZATION_FAILED | 知识库向量化失败 |

### AI 服务（7001-7005）

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 7001 | AI_SERVICE_UNAVAILABLE | AI 服务暂时不可用（握手失败） |
| 7002 | AI_SERVICE_TIMEOUT | AI 服务响应超时 |
| 7003 | AI_SERVICE_ERROR | AI 服务调用失败 |
| 7004 | AI_API_KEY_INVALID | AI 服务密钥无效 |
| 7005 | AI_RATE_LIMIT_EXCEEDED | AI 服务调用频率超限 |

### 限流（8001）

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 8001 | RATE_LIMIT_EXCEEDED | 请求过于频繁，请稍后再试 |

### 面试日程（9001）

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 9001 | INTERVIEW_SCHEDULE_NOT_FOUND | 面试日程不存在 |

### 语音面试（10001-10006）

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 10001 | VOICE_SESSION_NOT_FOUND | 语音面试会话不存在 |
| 10004 | VOICE_EVALUATION_FAILED | 语音面试评估失败 |
| 10006 | VOICE_EVALUATION_NOT_FOUND | 语音面试评估结果不存在 |

### Provider 管理（11001-11011）

| 错误码 | 枚举名 | 含义 |
|--------|--------|------|
| 11001 | PROVIDER_NOT_FOUND | LLM Provider 不存在 |
| 11002 | PROVIDER_ALREADY_EXISTS | LLM Provider 已存在 |
| 11004 | PROVIDER_CONFIG_READ_FAILED | 读取 Provider 配置失败 |
| 11005 | PROVIDER_CONFIG_WRITE_FAILED | 写入 Provider 配置失败 |
| 11006 | PROVIDER_TEST_FAILED | Provider 连通性测试失败 |
| 11007 | PROVIDER_DEFAULT_CANNOT_DELETE | 默认 Provider 不可删除 |
| 11008 | MODULE_NOT_FOUND | 模块不存在 |
| 11009 | VOICE_CONFIG_READ_FAILED | 读取语音服务配置失败 |
| 11010 | VOICE_CONFIG_WRITE_FAILED | 写入语音服务配置失败 |
| 11011 | VOICE_CONFIG_TEST_FAILED | 语音服务连通性测试失败 |

---
## 附录 B：限流接口清单

| 模块 | 接口 | 限流规则 |
|------|------|----------|
| 面试 | POST `/api/interview/sessions` | GLOBAL=5/s + IP=5/s |
| 面试 | POST `.../answers` | GLOBAL=10/s |
| 技能 | POST `/parse-jd` | IP=5/s |
| 知识库 | POST `/query` | GLOBAL=10/s + IP=10/s |
| 知识库 | POST `/query/stream` | GLOBAL=5/s + IP=5/s |
| 知识库 | POST `/upload` | GLOBAL=3/s + IP=3/s |
| 知识库 | POST `/{id}/revectorize` | GLOBAL=2/s + IP=2/s |
| 简历 | POST `/upload` | GLOBAL=5/s + IP=5/s |
| 简历 | POST `/{id}/reanalyze` | GLOBAL=2/s + IP=2/s |
| Provider | 所有 15 个接口 | 读=30/s, 写=5/s, 测试=10/s（均 GLOBAL） |

**规律**：AI 密集型操作（上传/分析/查询/重试）限流较严（2-5/s），纯读操作较宽松（30/s）。

---

## 附录 C：FastAPI APIRouter 分组建议

| APIRouter | 前缀 | 对应 Controller | 接口数 | 说明 |
|-----------|------|-----------------|--------|------|
| `interview_router` | `/api/interview` | InterviewController + InterviewSkillController | 15 | 模拟面试 + 技能管理 |
| `schedule_router` | `/api/interview-schedule` | InterviewScheduleController | 7 | 面试日程管理 |
| `knowledgebase_router` | `/api/knowledgebase` | KnowledgeBaseController | 14 | 知识库文件管理 + 向量化 |
| `rag_chat_router` | `/api/rag-chat` | RagChatController | 8 | RAG 聊天会话 |
| `llm_provider_router` | `/api/llm-provider` | LlmProviderController | 15 | LLM/ASR/TTS 供应商配置 |
| `resume_router` | `/api/resumes` | ResumeController | 7 | 简历上传与分析 |
| `voice_interview_router` | `/api/voice-interview` | VoiceInterviewController | 10 | 语音面试 REST |
| `voice_interview_ws` | `/ws/voice-interview/{session_id}` | WebSocketHandler | - | 语音面试实时双向音频流 |

---

## 附录 D：Java 特性迁移对照表

| Java 特性 | Python/FastAPI 对应 |
|-----------|-------------------|
| `@RestControllerAdvice` | FastAPI `@app.exception_handler` |
| `@Transactional` | SQLAlchemy `session.begin()` |
| Spring AOP | Python 装饰器 |
| Redis Stream Consumer Group | `redis.asyncio` stream（XREADGROUP/XADD/XAUTOCLAIM） |
| Redisson | `redis.asyncio` |
| 虚拟线程 | `asyncio` / `anyio` |
| Spring AI ChatClient | LangChain/LangGraph ChatModel |
| `@Scheduled` | APScheduler |
| `TransactionSynchronization.afterCommit` | SQLAlchemy 事件监听 / 显式顺序控制 |
| `Flux<String>` SSE 流式 | `StreamingResponse` + `text/event-stream` |
| `MultipartFile` 文件上传 | `UploadFile` |
| `ResponseEntity<byte[]>` PDF 导出 | `Response` + `media_type='application/pdf'` |
| `Result<T>` 统一包装 | Pydantic 泛型模型 |
| `@RateLimit` AOP 限流 | `slowapi` 库装饰器 |
| `TextWebSocketHandler` | `@router.websocket` |
| `@CrossOrigin` / `CorsConfig` | `CORSMiddleware` |
| MapStruct | 手写映射函数 / Pydantic 模型转换 |
| Apache Tika | `unstructured` |
| iText 7 (PDF) | `WeasyPrint`（HTML->PDF） |
| Spring AI PgVectorStore | `pgvector` + LangChain `PGVector` |
| AWS SDK v2 (S3) | `aioboto3` |
| `CompletableFuture` 并行 | `asyncio.gather()` |

---

## 附录 E：异步任务流清单

| 任务 | Stream Key | 消费者组 | 触发时机 | 处理内容 | 状态字段 |
|------|-----------|---------|----------|----------|----------|
| 简历分析 | `resume:analyze:stream` | `analyze-group` | 简历上传后 | LLM 评分 + 持久化 | `Resume.analyzeStatus` |
| 面试评估 | `interview:evaluate:stream` | `evaluate-group` | 面试完成/提前交卷 | LLM 分批评估 + 汇总 | `InterviewSession.evaluateStatus` |
| 知识库向量化 | `knowledgebase:vectorize:stream` | `vectorize-group` | 知识库上传后 | 文档分块 + Embedding + 写入 pgvector | `KnowledgeBase.vectorStatus` |
| 语音面试评估 | `voice:evaluate:stream` | `voice-evaluate-group` | 语音面试结束 | LLM 评估语音对话 | `VoiceInterviewSession.evaluateStatus` |

**Consumer 消费循环**（所有 4 套共享骨架）：

1. 回收超时 Pending 消息（XAUTOCLAIM, idle>5min）
2. 阻塞读取新消息（XREADGROUP, 超时1s）
3. 对每条消息：shouldSkip 检查 -> markProcessing -> processBusiness -> markCompleted -> ACK
4. 失败重新入队（最多重试3次），超过 MAX_RETRY -> markFailed

**常量**：BATCH_SIZE=10, POLL_INTERVAL=1000ms, PENDING_IDLE_TIMEOUT=5min, MAX_RETRY=3, STREAM_MAX_LEN=1000

---

## 附录 F：语音面试阶段配置

| 阶段 | 最小时长 | 建议时长 | 最大时长 | 最小问题数 | 最大问题数 |
|------|---------|---------|---------|-----------|-----------|
| INTRO | 3min | 5min | 8min | 2 | 5 |
| TECH | 8min | 10min | 15min | 3 | 8 |
| PROJECT | 8min | 10min | 15min | 2 | 5 |
| HR | 3min | 5min | 8min | 2 | 5 |

**阶段切换规则**：
- 规则1：达到 maxDuration -> 强制切换
- 规则2：达到 maxQuestions -> 建议切换
- 规则3：达到 suggestedDuration 且 >= minQuestions -> 建议切换

**其他语音配置**：
- AI 回复最大长度：120 字符
- 并发 TTS 上限：3
- TTS 超时：8 秒
- 会话缓存 TTL：1 小时
- 暂停超时警告：4分30秒
- 暂停超时自动暂停：5分钟
- ASR 重连：最多 2 次，每次延迟 10 秒
- 回声抑制冷却期：800ms

---

## 附录 G：Grilling 修正补充

> 以下决策在 grilling 会话中确认，补充原文未覆盖的内容。对应 ADR 见 `docs/adr/`。

### G.1 部署并发模型：单 worker（ADR-0005）

Python 用 `uvicorn --workers 1` + asyncio 并发，与 Java 单进程 + 虚拟线程等价。消除多 worker 下的消费者重复消费、APScheduler 重复触发、WebSocket 跨进程等问题。AI 应用 I/O 密集型，asyncio 单进程足够。水平扩展可后续通过多容器 + Redis 协调实现。

### G.2 LLM 调用重试分层

| 层 | 参数 | 处理的错误 | 与 Java 对应 |
|----|------|-----------|-------------|
| SDK 层 | `ChatOpenAI(max_retries=2)` | 429/5xx/网络错误 | Java `spring.ai.retry.max-attempts=1`（Python 加大，因 SDK 只重试传输错误） |
| 业务层 | `tenacity` 重试 2 次 | 结构化输出 JSON 解析失败 | Java `structured-max-attempts: 2` |

两层互不干扰。业务层重试时追加修复提示词 + 上次错误信息（与 Java 一致）。

### G.3 时间/时区策略

- 数据库：存 aware datetime（UTC）
- API 序列化：Pydantic 输出带时区后缀的 ISO 8601（如 `2026-07-14T12:00:00+00:00`）
- 前端 `new Date()` 自动转为本地时区显示，与 Java 的 `LocalDateTime` 行为在前端显示上一致
- **注意**：Java 返回无时区后缀的本地时间字符串，Python 返回带时区后缀的 UTC 字符串，前端 `new Date()` 均能正确解析

### G.4 评估服务并行分批

Java 顺序分批（batch_size=8），Python 用 `asyncio.gather` + `asyncio.Semaphore(3)` 并行各批。并发数 3 对多数 LLM 供应商安全。某批失败返回 None，后续零分兜底（与 Java 一致）。

### G.5 认证策略（ADR-0007）

不实现认证（与 Java 一致）。限流 USER 维度可选：无 `X-User-Id` header 时跳过 USER 规则，仅执行 GLOBAL + IP。

### G.6 Prompt 模板格式

`.st` 文件用 `{varName}` 占位符，与 LangChain `PromptTemplate` 默认格式直接兼容，无需改语法。

### G.7 知识库分块

LangChain `TokenTextSplitter`，~800 tokens/chunk，标点边界切分，无重叠，embedding batch ≤ 10（与 Java Spring AI `TokenTextSplitter` 默认配置一致）。

### G.8 文件名拼音转换

`pypinyin` 全拼无声调 + 首字母大写（大驼峰），非汉字字符保留（与 Java pinyin4j 一致）。

### G.9 API Key 加密

`cryptography` AES-GCM，密钥从环境变量 `APP_AI_CONFIG_ENCRYPTION_KEY` 读，启动时必须提供，不允许 fallback（与 Java 一致）。
