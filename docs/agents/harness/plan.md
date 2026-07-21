# Harness Engineering 改进计划

> 基于 R1+R2 review 后的 harness engineering 分析，经三轮文献调研修正时机。
>
> 参考来源：
> - [OpenAI Codex: harness engineering](https://openai.com/index/harness-engineering/) - "constraints are an early prerequisite, not a postpone"
> - [Martin Fowler: harness engineering for coding agent users](https://martinfowler.com/articles/harness-engineering.html) - feedforward/feedback 模型，"keep quality left"
> - [harness-engineering.net](https://harness-engineering.net/) - 四维度框架 + 20 点清单
> - [Augment Code: harness engineering guide](https://www.augmentcode.com/guides/harness-engineering-ai-coding-agents) - "constraint harnesses first"
> - [Harness Model Maturity Matrix](https://handsonarchitects.com/blog/2026/the-harness-model-ai-engineering-maturity-matrix/) - "sprint-aligned investment"，greenfield 从 Stage 3 起步
> - [ArchUnitPython](https://lukasniessen.medium.com/architecture-testing-in-python-with-archunitpython-8c4017b6b819) - "Start small. Pick the one thing that keeps going wrong."

## 核心判断

本项目是 **agent-first greenfield** 项目（所有代码由 AI agent 编写）。Stages 0-3 产生了多处架构违规（GradingService 命名违反词汇表、ErrorCode 双导入源、consumer 重复代码），花了 9 个 commit 修复。这些违规**本可被架构 fitness 测试自动捕获**。

Stage 4（文字面试，P0 核心，3 issue，6-8 天）是最复杂的业务逻辑。**无架构守卫则违规复利积累**，R3 review 时重复修复痛苦。

因此：**F1 架构 fitness 测试是 Stage 4 的前置条件，不是后置收尾。**

## 当前状态评估

| 维度 | 评级 | 说明 |
|------|------|------|
| Feedforward（引导） | 强 | AGENTS.md 地图、CONTEXT.md 词汇表、ADR 0001-0009、Skills 即时加载 |
| Feedback（传感器） | 中强 | pytest 309 + ruff + mypy + pre-commit + /code-review 双轴，缺架构 fitness test |
| Infrastructure | 中 | MCP（context7 + github）+ LSP + sub-agent，缺隔离和可观测性 |
| Team Processes | 强 | 原子提交、复审阈值、上下文维护清单，缺 GC loop 和度量 |

## 缺失清单

### Feedforward（引导）

| # | 缺失 | 修复方案 | 工作量 |
|---|------|---------|--------|
| ✅ F1 | 架构方向无机械执行 | `tests/test_architecture.py`：①domain 层禁止导入 fastapi/sqlalchemy/app.infrastructure/app.application/app.api ②domain 层仅允许 import 标准库 ③ADR-0008 禁止 SQLAlchemy after_commit 事件注册。用 `ast` 解析，无需新依赖。**已完成（1d255de），ADR-0008 守卫已扩展** | 1h |
| F2 | 无已拒绝方案清单 | 新建 `docs/rejected-ideas.md`，汇总 ADR + 迁移计划中已否决的方案+理由 | 30min |
| ✅ F3 | infrastructure->application 依赖无 ADR | 新建 `docs/adr/0012-infrastructure-consumer-application-dependency.md`（0010 号已被 parse-jd 占用，落为 0012）。**已完成（#19）**，配套 `test_architecture.py` 白名单棘轮守卫 | 15min |
| F16 | application->api 分层无守卫 + BaseSchema 位置不当 | `tests/test_architecture.py` 扩展：禁止 application 导入 app.api。前置：BaseSchema 从 `app/api/responses.py` 迁出（当前 8 文件导入 `app.api.responses.BaseSchema`），需重构决策。Stage 7 准备阶段决定 3-A 延期 | 待定 |

### Feedback（传感器）

| # | 缺失 | 修复方案 | 工作量 |
|---|------|---------|--------|
| ✅ F4 | CI 缺 `ruff format --check` | ci.yml 加 `uv run ruff format --check .` 步骤。**已完成（4a7d5c3）** | 5min |
| ✅ F5 | 文档漂移无自动检测 | `tests/test_doc_drift.py`：扫描 `docs/**/*.md` 中的文件路径引用，断言路径存在。**已完成** | 1h |
| F6 | Review finding 未回馈 harness | `tests/test_glossary.py`：解析 CONTEXT.md `_Avoid_` 词条，扫描代码类名/函数名，断言不包含 | 1h |
| F7 | 无覆盖率阈值 | pyproject.toml 加 `fail_under`（需先确认基线） | 15min |
| F8 | 无 E2E/集成测试 | 后续阶段：docker-compose + pytest integration 标记 | 2-3d |

### Infrastructure

| # | 缺失 | 修复方案 | 工作量 |
|---|------|---------|--------|
| F9 | 无 per-worktree 隔离 | 需 opencode 运行时支持 | - |
| F10 | 运行时可观测性未暴露 | 后续阶段：结构化日志 + Prometheus | 3-5d |
| F11 | `nul` 文件反复出现 | 排查创建源或加 pre-commit 清理 | 30min |

### Team Processes

| # | 缺失 | 修复方案 | 工作量 |
|---|------|---------|--------|
| ✅ F12 | 无 garbage collection loop | AGENTS.md §9 补充：每次 HARD 违反必须新增结构测试/lint 防复发。**已完成** | 15min |
| F13 | 无 harness 质量度量 | `docs/agents/harness-coverage.md`：跟踪规则数 / 机械执行数 / 覆盖率 | 30min |
| ✅ F14 | CI 不运行 `make verify` | F4 使 CI 步骤（lint+format-check+typecheck+test）与 `make verify` 对齐。**已完成，F4 附带达成** | 15min |
| ✅ F15 | 提交前 review 闸门无强制 | AGENTS.md §9 补充 scoped 规则：涉及 `app/` 或 `tests/` 代码改动的实施任务，todo 清单必含 `/code-review` 为提交前倒数第二步。**已完成（5024515）** | 15min |

## 实施时机与步骤

### 第一批：Stage 4 之前（立即）

> 理由：OpenAI "constraints are an early prerequisite"；Augment Code "constraint harnesses first"。
> domain 层当前干净（仅 import enum），F1 测试立即绿灯，从 day 1 守护。

#### F1: 架构 fitness 测试

**文件**：`tests/test_architecture.py`

**规则**（用 stdlib `ast` 解析，无需新依赖）：

1. **domain 层零框架依赖**：扫描 `app/domain/**/*.py` 的所有 import，禁止：
   - `fastapi`、`sqlalchemy`、`pydantic`、`langchain`、`redis`、`slowapi`
   - `app.infrastructure`、`app.application`、`app.api`、`app.config`
2. **domain 层仅允许标准库**：所有 import 必须在 `sys.stdlib_module_names` 中或为 `app.domain` 内部引用

**实现要点**：
- 用 `ast.walk` 遍历 AST 节点，收集 `Import` 和 `ImportFrom` 节点
- 对每个 import，取顶层模块名，检查是否在禁止列表中
- 报错信息要 actionable：`"domain 层禁止导入 sqlalchemy（AGENTS.md §4: domain 层零框架依赖）"`

**验证**：`uv run pytest tests/test_architecture.py -v` 全绿（当前 domain 仅 import enum）

**提交**：`test(architecture): 新增 domain 层纯度 fitness 测试`

#### F4: CI 补全 format check

**文件**：`.github/workflows/ci.yml`

**改动**：在 "Lint (ruff)" 步骤后加：
```yaml
      - name: Format check (ruff)
        run: uv run ruff format --check .
```

**提交**：`ci: 补全 ruff format --check 步骤`

**验证**：`uv run ruff format --check .` 本地通过

### 第二批：Stage 4 期间（sprint-aligned）

> 理由：Harness Model "sprint-aligned investment: every sprint, the harness gets one of its dimensions sharpened"。
> 不阻塞功能交付，每个 issue 完成后追加一项。

#### F2: 已拒绝方案清单

**时机**：Stage 4 第一个 issue 完成后

**文件**：`docs/rejected-ideas.md`

**内容**：从 ADR 0001-0009 + 迁移计划 D1-D6 提取已否决方案：
- Celery（选 redis.asyncio Stream，D2）
- ORM 自动迁移（选 Alembic，D6/ADR-0002）
- SQLAlchemy-pgvector 扩展（选手写 pgvector，ADR-0006）
- application.yml 中间层（选数据库直存，ADR-0004）
- 等

**提交**：`docs: 新增已拒绝方案清单`

#### F5: 文档漂移检测

**时机**：Stage 4 第二个 issue 完成后（此时 docs/ 可能有新增引用）

**文件**：`tests/test_doc_drift.py`

**规则**：扫描 `docs/**/*.md` 中的反引号包裹的文件路径（如 `` `api/errors.py` ``），断言路径在 repo 中存在

**实现要点**：
- 用 `re.findall` 提取单行反引号内容（排除跨行代码块）
- 过滤：须**同时**含 `/` 且以已知扩展名结尾（.py/.md/.yml/.yaml/.toml/.sql/.json/.lua/.cfg/.ini/.ttf/.ts/.j2/.st）。AND 逻辑比原 OR 更精确--OR 会让裸文件名（`main.py`）误报且无法解析子目录
- 排除：以 `/`/`~` 开头、含 `://`、含特殊字符（`*?{}=<>` 空格）
- 解析基：repo 根 / `app/` / `docs/` / `tests/` / 文档所在目录，任一存在即合法
- `KNOWN_MISSING` 白名单：已登记的计划未建文件（后续阶段交付、harness F2/F3/F6/F13）与历史记录引用（pitfalls.md 描述已删/重命名文件）。文件创建后应移除以使守卫重新生效
- 报错：`"docs/migration-plan.md 引用了不存在的文件路径: api/errors.py"`

**提交**：`test(docs): 新增文档漂移检测测试`

#### F12: GC loop 流程

**时机**：Stage 4 R3 review 发现第一个 HARD 违反后

**文件**：`AGENTS.md` §9 追加

**内容**：
```
- 复审后若发现 HARD 违反，必须新增一个结构测试或 lint 规则防止同类违规复发
- 纯 finding 响应式小修无需新增规则
```

**提交**：`docs(agents): §9 补充 GC loop 规则`

### 第三批：Stage 4 之后

> 理由：需要更多代码才有意义。F6 需要更多类名才能检测词汇表违规。F7 需要足够测试才能设覆盖率基线。

#### F6: 词汇表执行测试

**文件**：`tests/test_glossary.py`

**规则**：解析 CONTEXT.md 中所有 `_Avoid_:` 后的词条，扫描 `app/**/*.py` 中的类名/函数名/变量名，断言不包含 avoid 词条

**实现要点**：
- 用正则提取 `_Avoid_:` 行后的逗号分隔词条
- 用 `ast` 扫描代码中的 ClassDef/FunctionDef/Name 节点
- 跳过 test 文件（测试中可能引用 avoid 词条做断言）

#### F3: ADR for infrastructure->application ✅（#19 完成）

**文件**：`docs/adr/0012-infrastructure-consumer-application-dependency.md`（0010 号已被 parse-jd ADR 占用，落为 0012）

**内容**：记录 consumer（infrastructure）import application service 的妥协理由：consumer 属宿主/驱动角色，调用应用服务是常见模式。边界：仅 application service 可被反向导入，pure codec/adapter 须置 domain。配套 `test_architecture.py::test_infrastructure_imports_application_only_via_allowlist` 白名单棘轮守卫机械执行

#### F7: 覆盖率阈值

**文件**：`pyproject.toml`

**步骤**：先运行 `uv run pytest --cov=app --cov-report=term` 确认当前覆盖率，设 `fail_under` 为当前值 - 2%（留缓冲）

#### F11/F13/F14: 杂项

- F11: 排查 `nul` 创建源（可能是 bash 重定向到 NUL）
- F13: 新建 `docs/agents/harness-coverage.md`，跟踪规则数/机械执行数
- F14: ci.yml 确认步骤与 `make verify` 对齐

### 第四批：后续阶段（P3）

> 理由：需要基础设施稳定。F8 需要真实 PG/Redis/MinIO。F9-F10 需要平台支持。

| # | 内容 | 时机 |
|---|------|------|
| F8 | E2E/集成测试 | 基础设施稳定后（Stage 5+） |
| F9 | per-worktree 隔离 | 需 opencode 运行时支持 |
| F10 | 运行时可观测性 | Stage 6+，业务功能基本完整后 |

## 验证方式

| 编号 | 验证方式 |
|------|---------|
| F1/F5/F6 | 随 `make verify` 运行，违反即失败 |
| F4/F14 | CI pipeline 在 push 时自动执行 |
| F2/F3/F12/F13 | 文档变更，人工确认 |
| F7 | `make verify` 中 pytest 输出覆盖率，低于阈值即失败 |

## 参考工具（未来可选引入）

当前 F1 用 stdlib `ast` 实现，无需新依赖。若未来需要更复杂规则（层序、循环检测、指标），可选：

| 工具 | 特点 | 引入时机 |
|------|------|---------|
| [PyTestArch](https://github.com/zyskarch/pytestarch) | ArchUnit 风格，fluent API，层规则 | 需要层序/循环检测时 |
| [ArchUnitPython](https://github.com/LukasNiessen/ArchUnitPython) | ast 解析，零依赖，自定义规则+指标 | 需要代码指标（LCOM/文件行数）时 |
| [archetype-py](https://github.com/nvphungdev/archetype-py) | 装饰器风格，CI 友好 | 需要 `@warn`/`@skip`/`@since` 精细控制时 |
| [pytest-imports](https://github.com/nwilbert/pytest-imports) | 轻量 import 规则插件 | 只需 import 规则时 |
