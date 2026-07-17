# Harness Engineering 改进计划

> 基于 R1+R2 review 后的 harness engineering 分析。
> 参考来源：OpenAI Codex harness engineering 实践、Martin Fowler feedforward/feedback 模型、harness-engineering.net 四维度框架。

## 当前状态评估

| 维度 | 评级 | 说明 |
|------|------|------|
| Feedforward（引导） | 强 | AGENTS.md 地图、CONTEXT.md 词汇表、ADR 0001-0009、Skills 即时加载 |
| Feedback（传感器） | 中强 | pytest 309 + ruff + mypy + pre-commit + /code-review 双轴，缺架构 fitness test |
| Infrastructure | 中 | MCP（context7 + github）+ LSP + sub-agent，缺隔离和可观测性 |
| Team Processes | 强 | 原子提交、复审阈值、上下文维护清单，缺 GC loop 和度量 |

## 缺失清单

### Feedforward（引导）

| # | 缺失 | 修复方案 | 工作量 | 优先级 |
|---|------|---------|--------|--------|
| F1 | 架构方向无机械执行 | `tests/test_architecture.py`：①domain 层禁止导入 fastapi/sqlalchemy/app.infrastructure/app.application/app.api ②domain 层仅允许 import 标准库。用 `ast` 解析，无需新依赖 | 1h | P0 |
| F2 | 无已拒绝方案清单 | 新建 `docs/rejected-ideas.md`，汇总 ADR + 迁移计划中已否决的方案+理由 | 30min | P1 |
| F3 | infrastructure->application 依赖无 ADR | 新建 `docs/adr/0010-infrastructure-consumer-application-dependency.md` | 15min | P2 |

### Feedback（传感器）

| # | 缺失 | 修复方案 | 工作量 | 优先级 |
|---|------|---------|--------|--------|
| F4 | CI 缺 `ruff format --check` | ci.yml 加 `uv run ruff format --check .` 步骤 | 5min | P0 |
| F5 | 文档漂移无自动检测 | `tests/test_doc_drift.py`：扫描 `docs/**/*.md` 中的文件路径引用，断言路径存在 | 1h | P1 |
| F6 | Review finding 未回馈 harness | `tests/test_glossary.py`：解析 CONTEXT.md `_Avoid_` 词条，扫描代码类名/函数名，断言不包含 | 1h | P1 |
| F7 | 无覆盖率阈值 | pyproject.toml 加 `fail_under`（需先确认基线） | 15min | P2 |
| F8 | 无 E2E/集成测试 | 后续阶段：docker-compose + pytest integration 标记 | 2-3d | P3 |

### Infrastructure

| # | 缺失 | 修复方案 | 工作量 | 优先级 |
|---|------|---------|--------|--------|
| F9 | 无 per-worktree 隔离 | 需 opencode 运行时支持 | - | P3 |
| F10 | 运行时可观测性未暴露 | 后续阶段：结构化日志 + Prometheus | 3-5d | P3 |
| F11 | `nul` 文件反复出现 | 排查创建源或加 pre-commit 清理 | 30min | P2 |

### Team Processes

| # | 缺失 | 修复方案 | 工作量 | 优先级 |
|---|------|---------|--------|--------|
| F12 | 无 garbage collection loop | AGENTS.md §9 补充：每次 HARD 违反必须新增结构测试/lint 防复发 | 15min | P1 |
| F13 | 无 harness 质量度量 | `docs/agents/harness-coverage.md`：跟踪规则数 / 机械执行数 / 覆盖率 | 30min | P2 |
| F14 | CI 不运行 `make verify` | ci.yml 改为 `make verify` 或确保步骤对齐 | 15min | P2 |

## 实施批次

| 批次 | 编号 | 内容 | 总工作量 | 时机 |
|------|------|------|---------|------|
| 第一批（P0） | F1 + F4 | 架构 fitness 测试 + CI format check | ~1h | Stage 4 功能开发前 |
| 第二批（P1） | F2 + F5 + F6 + F12 | 拒绝清单 + 文档漂移 + 词汇表执行 + GC loop | ~3h | 第一批后 |
| 第三批（P2） | F3 + F7 + F11 + F13 + F14 | ADR + 覆盖率 + nul + 度量 + CI 对齐 | ~1.5h | 第二批后 |
| 第四批（P3） | F8 + F9 + F10 | E2E + 隔离 + 可观测性 | 后续阶段 | 随业务推进 |

## 验证方式

- F1/F5/F6：新增测试随 `make verify` 运行，违反即失败
- F4/F14：CI pipeline 在 push 时自动执行
- F2/F3/F12/F13：文档变更，人工确认
- F7：`make verify` 中 pytest 输出覆盖率，低于阈值即失败
