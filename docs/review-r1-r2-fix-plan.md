# R1+R2 全量 Review 修复计划

> 基于 4861cff...HEAD（37 commits, app/ 75 files 3139 lines）双轴 code-review 结果。
> 经两份外部审查意见综合修正，含 11 个修改点（M1-M11）。

## Review 范围

| 阶段 | Issues | 内容 |
|------|--------|------|
| R1 | #2 #3 #4 | 项目骨架 + LLM 基础设施 + 异步任务/文件基础设施 |
| R2 | #5 #6 | 简历上传解析去重 + 简历异步分析 PDF 导出 |

## 聚合发现

### CRITICAL（Spec 缺失）

| # | Finding | 来源 |
|---|---------|------|
| F1 | llm_provider_config 表无迁移 - 001 建 vector_store，002 建 resumes，llm_provider_config 表从未创建，种子 Provider 静默失败 | Spec #2 |

### HIGH（Spec 偏差 + Standards 硬违反）

| # | Finding | 来源 |
|---|---------|------|
| F2 | PromptSanitizer 定义但从未集成 - 4类正则+UUID分隔符零调用，简历文本直接喂给 LLM | Spec #3 |
| F3 | tenacity 重试次数偏差 - max_attempts=2 = 2次总尝试，spec 重试2次 = 3次总尝试 | Spec #3 |
| F4 | GradingService 命名违反领域词汇表 - CONTEXT.md:25 Avoid: Grading，应为 ResumeAnalysisService | Standards |

### MEDIUM（Standards 异味）

| # | Finding | 来源 |
|---|---------|------|
| F5 | consumer 4处重复 open session -> get_by_id -> None-check -> log+return | Standards |
| F6 | ErrorCode 双导入源 - app.api.errors 是 re-export shim，14处引用应统一到 app.domain.errors | Standards |
| F7 | interview_count=0 死代码 - DTO 有字段，service 硬编码 0，面试模块未建 | Standards |

### LOW

| # | Finding | 来源 |
|---|---------|------|
| F8 | 3个未用 StreamConfig - INTERVIEW_EVALUATE/KB_VECTORIZE/VOICE_EVALUATE 为未来 issue 预定义 | Spec scope creep |

### 不修复（附理由）

| Finding | 理由 |
|---------|------|
| domain/services 提取降级逻辑 | 降级是简单 fallback，非复杂业务逻辑；实际评分由 LLM 完成 |
| analyze_status Primitive Obsession | SQLAlchemy 存 str 是标准模式；大重构低 ROI |
| Any 类型 (s3/parser) | aioboto3 client 类型难标注，基础设施层务实选择 |
| pdf.py 评分权重 | 展示元数据（PDF 表格 max_score），非评估算法 |
| 模块级 Limiter | slowapi 框架约定，非 DDD 服务 |
| mark_processing 幂等 gap | 加 PROCESSING 跳过会阻断崩溃任务恢复；并发重复概率低 |
| 降级链单 fallback | 降级链语义为优雅降级，单 fallback 合理 |
| Voice config / looks_like_chat_model | 无害防御性代码 |

## 审查修正点（M1-M11）

两份外部审查意见 + 自检，综合出 11 个修正点：

### 必须修改

| # | 修正点 | 来源 | 影响 |
|---|--------|------|------|
| M1 | 执行顺序：F4 重命名必须第一个 commit - git mv 已执行，deps.py/consumer.py 仍 import grading，代码当前不可运行 | 两份审查 | commit 顺序 |
| M2 | sanitize() 返回 None 的类型安全 - sanitize(str | None) -> str | None，空文本返回 None，wrap_with_delimiters 期望 str，需加 or 空字符串兜底 | Review 2 | Commit 5 代码 |
| M3 | 补充 PromptSanitizer import | Review 1 | Commit 5 代码 |
| M4 | 参数名/属性名统一重命名不留二选一 - grading_service->analysis_service, self._grading->self._analysis_service, get_grading_service->get_resume_analysis_service, _grading_service->_resume_analysis_service, start_resume_analyze_consumer 调用点同步 | 两份审查 | Commit 1 |
| M5 | helper 不一刀切加 warning log - mark_processing/process_business 的 None 有 warning，mark_completed/mark_failed 静默 return。helper 只做查询，log 由调用方决定 | 两份审查 | Commit 6 |
| M6 | 测试断言改为 mock PromptSanitizer - assert sanitize/wrap 被调用，而非弱断言 in | Review 1 | Commit 5 测试 |

### 需注意

| # | 修正点 | 来源 | 影响 |
|---|--------|------|------|
| M7 | 双重分隔符选 A 不改模板 - UUID 边界标签是真正防御边界，模板分隔符作为人类可读标记保留 | Review 2 | 不改动 |
| M8 | commit message 类型按 finding 分别使用 - fix/feat/refactor | Review 1 | commit messages |
| M9 | migration 003 不加额外索引 - ORM 无 unique 约束，migration 须与 ORM 对齐 | Review 2 | Commit 3 |

### 补充

| # | 修正点 | 来源 | 影响 |
|---|--------|------|------|
| M10 | 8 个原子提交拆分 - 每个独立可构建测试，F4 第一个 | 自检 | 整体结构 |
| M11 | 每 2-3 步跑一次 pytest - 避免最后一次性调试大量错误 | 两份审查 | 执行节奏 |

## 前置状态

git mv 已执行（grading.py -> analysis.py, test_grading.py -> test_analysis.py），但 import 路径和类名尚未更新，代码当前不可运行。Commit 1 必须首先修复此问题。

## 修复方案（9 个原子提交 + 增量 review）

### Commit 1: refactor(resume): GradingService 重命名为 ResumeAnalysisService（F4）

必须第一个，修复 git mv 后 broken imports。

**app/application/resume/analysis.py（已 mv）**：
- 类名 GradingService -> ResumeAnalysisService
- docstring 更新

**app/api/deps.py**：
- import 路径 grading -> analysis
- 类名/函数名/变量名：GradingService->ResumeAnalysisService, get_grading_service->get_resume_analysis_service, _grading_service->_resume_analysis_service
- start_resume_analyze_consumer 中 grading_service=get_grading_service() -> analysis_service=get_resume_analysis_service()

**app/infrastructure/tasks/resume_analyze_consumer.py**：
- import 路径 grading -> analysis
- 类型标注 GradingService -> ResumeAnalysisService
- 参数名 grading_service -> analysis_service
- 属性 self._grading -> self._analysis_service
- 调用处 self._grading.analyze_resume() -> self._analysis_service.analyze_resume()

**tests/application/resume/test_analysis.py（已 mv）**：
- @patch 路径 grading -> analysis
- GradingService -> ResumeAnalysisService
- import 路径 grading -> analysis

验证：uv run pytest

### Commit 2: refactor(api): ErrorCode 导入源统一到 domain.errors，删除 errors shim（F6）

- sed 替换 14 个文件：from app.api.errors import -> from app.domain.errors import
- 涉及文件：exception_handlers.py, rate_limit.py, responses.py, test_resume.py, test_analysis.py, test_service.py, test_embeddings.py, test_encryption.py, test_llm_registry.py, test_structured_output.py, test_parser.py, test_s3.py, test_repository.py, test_exception.py
- 删除 app/api/errors.py

验证：uv run pytest

### Commit 3: fix(infrastructure): 补建 llm_provider_config 表迁移（F1）

- 新建 alembic/versions/003_llm_provider_config.py
- 建表 llm_provider_config，列定义对齐 ORM 模型
- down_revision = 002
- M9：不加额外索引或 unique 约束

验证：uv run pytest

### Commit 4: fix(infrastructure): tenacity 重试次数 2->3 对齐 spec（F3）

- app/infrastructure/ai/structured_output.py:32 - max_attempts: int = 2 -> 3
- 测试中显式 max_attempts=2 和 =1 不动（测试重试机制本身，非默认值）

验证：uv run pytest && make verify

### Commit 5: feat(resume): 集成 PromptSanitizer 清洗简历文本（F2）

**app/application/resume/analysis.py**：
- 添加 import：from app.infrastructure.ai.prompt_sanitizer import PromptSanitizer（M3）
- __init__ 中实例化 self._sanitizer = PromptSanitizer()
- analyze_resume 中（M2 None 兜底）：
  - sanitized_text = self._sanitizer.sanitize(resume_text) or 空字符串
  - wrapped = self._sanitizer.wrap_with_delimiters("简历内容", sanitized_text)
  - user_prompt = user_tpl.format(resumeText=wrapped)
- M7：不修改 resume-analysis-user.st 模板

**tests/application/resume/test_analysis.py**（M6 mock sanitizer）：
- test_renders_user_prompt 改为 @patch PromptSanitizer
- 断言 sanitize.assert_called_once_with + wrap_with_delimiters.assert_called_once_with + format.assert_called_once_with

验证：uv run pytest && make verify

### Commit 6: refactor(resume): consumer 提取 _get_resume 消除重复（F5）

**app/infrastructure/tasks/resume_analyze_consumer.py**（M5 helper 只查询，log 由调用方决定）：
- 提取 _get_resume(session, resume_id) -> Resume | None，只做 get_by_id
- mark_processing / process_business：调用 _get_resume，None 时自行打 warning
- mark_completed / mark_failed：调用 _get_resume，None 时静默 return

验证：uv run pytest

### Commit 7: refactor(resume): 删除 interview_count 死代码（F7）

- app/application/resume/schemas.py - ResumeListItemDTO 删 interview_count: int
- app/application/resume/service.py:126 - 删 interview_count=0
- tests/api/test_resume.py:48 - 删 interview_count=0
- tests/application/resume/test_service.py:254 - 删 assert interview_count == 0

验证：uv run pytest

### Commit 8: refactor(infrastructure): 删除未用 StreamConfig 常量（F8）

- app/infrastructure/tasks/constants.py - 删 INTERVIEW_EVALUATE, KB_VECTORIZE, VOICE_EVALUATE

验证：make verify

### Commit 9: docs(agents): R2 阶段 review 标记完成

- docs/agents/review-plan.md - R2 行标记完成

验证：无需（纯文档）

## 执行流程

| 阶段 | 内容 | M11 验证节奏 |
|------|------|-------------|
| Phase 1 | 执行 Commit 1-9 | C1后pytest; C2-3后pytest; C4-5后pytest+make verify; C6-7后pytest; C8后make verify |
| Phase 2 | make verify 全绿 | 最终全量验证 |
| Phase 3 | 增量 /code-review：fixed point = 1158200，diff = 1158200...HEAD，双轴并行（Standards + Spec） | |
| Phase 4 | 若 review 发现新 finding -> 修复 -> make verify -> 视改动范围决定是否再次增量 review | |
| Phase 5 | review 通过后 push（待用户确认） | |

## 复审阈值评估（AGENTS.md 第9条）

| 触发条件 | 命中 | 原因 |
|----------|------|------|
| 超出原 finding 范围 | 是 | 9项修复跨多文件 |
| 触碰分层/接口契约 | 是 | 公共类重命名、删除 errors.py shim、consumer 接口变更 |
| 新增文件与公共抽象 | 是 | 新增 migration 003、analysis.py 重命名 |

结论：修复后必须对增量（自 1158200 后的 commit）再跑一轮 /code-review，在 push 之前完成。

## 涉及文件清单

| 操作 | 文件 |
|------|------|
| 新建 | alembic/versions/003_llm_provider_config.py |
| 已 mv | app/application/resume/grading.py -> analysis.py |
| 已 mv | tests/application/resume/test_grading.py -> test_analysis.py |
| 删除 | app/api/errors.py |
| 修改 | app/infrastructure/ai/structured_output.py |
| 修改 | app/api/deps.py |
| 修改 | app/infrastructure/tasks/resume_analyze_consumer.py |
| 修改 | app/api/exception_handlers.py |
| 修改 | app/api/rate_limit.py |
| 修改 | app/api/responses.py |
| 修改 | app/application/resume/schemas.py |
| 修改 | app/application/resume/service.py |
| 修改 | app/infrastructure/tasks/constants.py |
| 修改 | tests/application/resume/test_analysis.py |
| 修改 | tests/api/test_resume.py |
| 修改 | tests/application/resume/test_service.py |
| 修改 | tests/infrastructure/ai/test_embeddings.py |
| 修改 | tests/infrastructure/ai/test_encryption.py |
| 修改 | tests/infrastructure/ai/test_llm_registry.py |
| 修改 | tests/infrastructure/ai/test_structured_output.py |
| 修改 | tests/infrastructure/parsing/test_parser.py |
| 修改 | tests/infrastructure/storage/test_s3.py |
| 修改 | tests/infrastructure/vector/test_repository.py |
| 修改 | tests/test_exception.py |
| 修改 | docs/agents/review-plan.md |
