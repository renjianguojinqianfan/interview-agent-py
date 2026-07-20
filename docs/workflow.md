# 开发流程

详细描述 `/implement` 的完整工作流。AGENTS.md §9 列出核心规则，本文档提供操作细节与 rationale。

## 流程总览

```
规划 -> TDD -> /code-review -> /neat-freak（§7 上下文同步） -> commit -> 关闭 issue
```

不得颠倒。每个阶段的产出是下一阶段的输入。

## 0. 规划

### 时机

加载 `/implement` 技能后的第一步，在写任何代码之前。

### 内容

1. 读取 issue body（What to build + Acceptance criteria）
2. 探索代码库（现有模式、依赖链、断裂点）
3. 识别设计决策，需要时向用户提问确认
4. 制定实施计划（文件清单 + 实施顺序 + TDD 分组策略）
5. 用户确认后进入 TDD

### 不绑定技能

规划阶段不绑定特定技能，由 `/implement` 编排。如需压力测试计划，用户可触发 `/grilling`；如需维护领域术语，可触发 `/domain-modeling`。

## 1. TDD（测试驱动开发）

### vertical slice 原则

测试与实现交替推进（red -> green 循环）：
1. 写一个失败的测试（red）
2. 写最小实现使其通过（green）
3. 下一个测试

**禁止水平切片**：不得先写完所有实现再写所有测试，也不得先写完所有测试再写所有实现。方法数较多时可按功能分组（如 CRUD 为一组、默认供应商为一组、ASR/TTS 为一组），每组内逐个测试-实现交替。

### 适用范围

- **适用 TDD**：service 层方法、API 端点、领域服务算法
- **不适用 TDD**：ORM 模型、schemas、仓储（数据结构类，由上层测试覆盖）
- **重构不适用 TDD**：重构属于 review 阶段，不在 red -> green 循环内

## 2. /code-review（代码审查）

### 时机

TDD 完成、`make verify` 通过后。

### 范围

审查 `git diff <fixed-point>...HEAD`，fixed point 为该 issue 开始前的 HEAD。

### 双轴并行

- **Standards 轴**：代码是否符合 AGENTS.md 分层/异步/类型/DI 约定 + Fowler 代码异味
- **Spec 轴**：代码是否忠实实现 issue body 的 "What to build" + "Acceptance criteria"

两个子 agent 并行运行，聚合后修复 findings。

### 为什么在 /neat-freak 之前

code-review 审查纯净的代码 diff。如果 neat-freak 先跑，文档改动混入 diff 会干扰子 agent 聚焦代码审查（Spec 子 agent 可能将文档同步标记为 "scope creep"）。

### 复审阈值

首次 `/code-review` 后若改动满足以下任一条件，需对增量（diff 自首次 review 后的 commit）再跑一轮：

- 改动超出原 finding 范围
- 触碰分层 / 接口契约
- 新增文件与公共抽象

纯 finding 响应式小修无需复审。

### 豁免 review

纯文档 / 配置 / 依赖升级 / 单行修复可标注「豁免 review」跳过。

## 3. /neat-freak（上下文同步）

### 时机

code-review 完成（含 findings 修复）后、commit 前。

### 范围

按 AGENTS.md §7 检查以下文件是否需要同步：

- **AGENTS.md** - 行为边界、约定、命令等有变化时更新
- **CONTEXT.md** - 领域术语增减或含义变化时更新
- **docs/migration-plan.md** - 架构、目录结构、阶段任务有变化时更新
- **docs/agents/review-plan.md** - review 节奏或分组有变化时更新
- **docs/adr/** - 有非平凡架构决策时新建 ADR

### 为什么在 /code-review 之后

- code-review 可能修复 bug 改变行为，neat-freak 能感知修复后的最终状态，文档更准确
- neat-freak 只改文档，不改代码逻辑，不影响 code-review 结论

### 执行流程

neat-freak 自身分两阶段：

1. **阶段一·盘点**：只产出清理计划，不改文件
2. **阶段二·执行**：用户确认后落地

## 4. commit（提交）

### 前置条件

- `make verify` 通过（pytest + ruff + format + mypy）
- /code-review findings 已修复
- /neat-freak 上下文同步已完成
- 已获用户确认（**禁止未经确认的提交**）

### 原子提交

每个 commit 是一个完整、可独立构建测试的逻辑变更。大功能拆分为多个原子提交（如：ORM + 迁移 -> service + API -> 文档同步）。

### commit message 格式

见 AGENTS.md §8。

## 5. 关闭 issue

commit 并推送后，关闭对应 GitHub issue（state: completed），附完成总结评论。

## 关键转折点操作

以下转折点必须重新加载对应技能 SKILL.md 逐字对照，不凭记忆：

| 转折点 | 重新加载 | 对照内容 |
|--------|---------|---------|
| 规划完成准备实现 | `/implement` | 确认进入 TDD 阶段 |
| 实现完成准备 review | `/implement` | 确认进入 review 阶段 |
| review 完成 | `/neat-freak` | 执行上下文同步流程 |
| 上下文同步完成准备提交 | `/implement` | 逐字对照 §9 流程顺序 |

长对话中上下文会稀释早期加载的技能内容，todo list 和重新加载是对冲手段。

## 异常流程技能

以下技能不在标准流程中，在特定条件下按需触发：

| 触发条件 | 技能 | 说明 |
|---------|------|------|
| 用户想压力测试计划 | `/grilling` | 在规划阶段对计划追问，发现盲点 |
| code-review 发现顽固 bug | `/diagnosing-bugs` | 诊断循环，定位根因 |
| 引入复杂领域术语 | `/domain-modeling` | 维护 CONTEXT.md + ADR，与 neat-freak 互补 |
| TDD 产生碎片提交需整理 | `/squash-and-split` | 将碎片提交压缩为语义化原子提交 |
| 遇到合并冲突 | `/resolving-merge-conflicts` | 解决 merge/rebase 冲突 |
| 对话过长需交接 | `/handoff` | 压缩为交接文档供新会话接手 |
