# AGENTS.md - interview-agent-py

> 本文件为 AI 编程助手的核心指令集，优先级高于所有口头约定。

## 1. 项目快照

- **项目名称**：interview-agent-py
- **一句话描述**：基于 LangGraph 的智能面试官平台后端，提供简历分析、模拟面试、RAG 知识库检索等能力。
- **项目类型**：`backend`（Python Web 服务）
- **技术栈**：
  - Python 3.13 + uv（包管理）+ FastAPI（Web 框架）
  - SQLAlchemy 2.0（async）+ PostgreSQL + pgvector（数据持久化与向量检索）
  - LangGraph（AI Agent 编排）
  - pytest（测试）+ ruff（代码规范）+ mypy（类型检查）

## 2. 常用命令

```bash
# 依赖安装
uv sync

# 开发服务器
uv run uvicorn app.main:app --reload    # -> http://localhost:8000

# 测试
uv run pytest                            # 运行所有测试

# 代码规范
uv run ruff check .                      # lint 检查
uv run ruff format .                     # 代码格式化

# 类型检查
uv run mypy app/                         # 提交前必须通过

# 一键质量门禁（推荐提交前运行）
make verify
```

## 3. 目录结构（DDD 分层）

- `app/api/` - API 路由层（FastAPI Router，仅做路由、校验和委托）
- `app/application/` - 应用服务层（业务编排，事务边界）
- `app/domain/` - 领域层（实体、值对象、领域服务、仓储接口）
- `app/infrastructure/` - 基础设施层（仓储实现、外部服务适配器、数据库模型）
- `app/config/` - 配置管理（环境变量、应用配置）
- `tests/` - 测试代码（单元测试 + 集成测试，镜像 app/ 目录结构）
- `.githooks/` - Git hooks（commit-msg + pre-commit，通过 `core.hooksPath` 配置）
- `Makefile` - 质量门禁命令

## 4. 关键约定

### 必须遵守
- **改代码前先说明计划**：不得直接改代码，必须先向用户确认方案
- **一个对话 = 一个任务**：不混杂多个不相关的改动
- **类型注解必须完整**：所有函数签名必须有类型注解，新增代码必须通过 `uv run mypy app/`
- **异步优先**：数据库操作和外部 I/O 使用 async/await，禁止在异步上下文中调用同步阻塞 I/O
- **分层依赖方向**：api -> application -> domain，infrastructure 实现 domain 定义的接口，依赖方向不可逆。简单 CRUD 模块可不经过 domain 层（application 直接调 infrastructure），但复杂业务逻辑（评估算法、出题策略等）必须隔离到 domain/services/ 作为纯函数/类，接收 dataclass、返回 dataclass，不依赖任何框架
- **domain 层零框架依赖**：禁止在 domain 层引入 FastAPI 或 SQLAlchemy。domain 层只放纯 Python（枚举、dataclass、领域服务算法、Protocol 接口）。SQLAlchemy 模型留 infrastructure/db/models/
- **依赖注入**：使用 FastAPI 的 `Depends` 进行依赖注入，禁止在模块级别直接实例化服务
- **禁止硬编码密钥**：API Key、数据库密码等敏感信息只放 `.env`，通过 `app/config/` 读取，不得提交到 Git

### 禁止事项
- 禁止提交未经用户确认的代码
- 禁止执行 `git push`，除非用户在单次对话中明确提出 push

## 5. 行为边界

- ✅ **允许**：修改 `app/` 和 `tests/` 下代码；运行测试与类型检查；编写单元测试
- ⚠️ **需确认**：修改 `pyproject.toml` 依赖

## 6. 完成定义（Definition of Done）

一个任务真正"完成"的标志（全部满足）：

1. `uv run pytest` 全部通过
2. `uv run ruff check .` 通过
3. `uv run ruff format --check .` 通过
4. `uv run mypy app/` 通过
5. 已获用户确认（**禁止未经确认的提交**）

等价快捷方式：`make verify` 一键全检通过（test + typecheck + lint + format-check）。

## 7. 上下文维护

每次开发完成后，必须检查以下文件是否需要同步：

- **AGENTS.md** - 行为边界、约定、命令等有变化时更新
- **CONTEXT.md** - 领域术语增减或含义变化时更新（参见 `docs/agents/domain.md`）
- **docs/migration-plan.md** - 架构、目录结构、阶段任务有变化时更新
- **docs/agents/review-plan.md** - review 节奏或分组有变化时更新

Git hooks 位于 `.githooks/` 目录（通过 `core.hooksPath` 配置），自动执行质量门禁，无需手动维护：

- `pre-commit` - 提交前运行 `pytest` + `ruff check` + `mypy`，失败阻止提交
- `commit-msg` - 校验 commit message 格式（`<type>(<scope>): <subject>`），不符合阻止提交

## 8. Git 提交规范

- commit message 格式：`<type>(<scope>): <subject>`
- type 可选：`feat` / `fix` / `docs` / `style` / `refactor` / `perf` / `test` / `build` / `ci` / `chore` / `revert`
- scope（可选）：标识改动范围，如 `api` / `domain` / `infrastructure` / `config` / `hooks` / `ci` 等
- subject 用中文，一句话说清改动
- 示例：`feat(api): 新增简历上传接口`
- **原子提交**：每个 commit 是一个完整、可独立构建测试的逻辑变更，不把多个不相关的修复堆在一个 commit 里

## 9. 技能执行纪律

- 加载技能后立即用 todowrite 拆解步骤，按顺序执行，不得跳步或颠倒
- `/implement` 的顺序是：TDD -> `/code-review` -> commit -> 关闭 issue，不得颠倒
- **提交前 review 闸门**：凡涉及 `app/` 或 `tests/` 下代码逻辑改动的实施任务，todo 清单必须把 `/code-review` 列为提交前倒数第二步（commit 为最后一步）；纯文档/配置/依赖升级/单行修复可标注「豁免 review」跳过
- **复审阈值**：首次 `/code-review` 后若改动超出原 finding 范围、触碰分层/接口契约、或新增文件与公共抽象，三者任一命中即对增量（diff 自首次 review 后的 commit）再跑一轮；纯 finding 响应式小修无需复审
- 关键转折点（如"实现完成准备提交"）重新加载技能 SKILL.md 逐字对照，不凭记忆
- 长对话中上下文会稀释早期加载的技能内容，todo list 和重新加载是对冲手段

## Agent skills

### Issue tracker

Issues are tracked as GitHub issues in `renjianguojinqianfan/interview-agent-py` (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical triage labels used as-is (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context - one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
