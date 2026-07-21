# Review 规划

两层 review 体系：单 issue review（实现正确性）+ 阶段 review（集成正确性）。

## 第一层：单 Issue Review

**时机**：每个 issue 的 `make verify` 通过后、提交后、进入下一个 issue 前。

**重点**：这个 issue 的代码是否正确实现了它的 acceptance criteria。

| 维度 | 检查内容 |
|------|---------|
| 逻辑正确性 | 状态机流转、边界条件、错误处理路径 |
| Spec 符合度 | 对照 issue body 的 "What to build" + "Acceptance criteria" 逐条验证 |
| Standards | AGENTS.md 分层/异步/类型/DI + Fowler 代码异味 |
| 测试覆盖 | 是否覆盖核心路径 + 异常路径 |

**Fixed point**：该 issue 开始前的 HEAD。

**流程**：`/code-review` 双轴并行（Standards + Spec），聚合后修复。

## 第二层：阶段 Review

**时机**：该阶段所有 issue 完成且各自单 issue review 通过后。

**重点**：跨 issue 集成是否正确，阶段业务闭环是否跑通。

| 维度 | 检查内容 |
|------|---------|
| 数据流完整性 | 阶段内 issue 之间的数据传递是否正确 |
| 架构一致性 | 跨 issue 的 DDD 分层是否统一，共享基础设施用法是否一致 |
| 规格符合度 | 对照迁移计划阶段描述 + PRD，验证阶段验收标准 |
| 重复/冲突 | 多个 issue 是否引入重复代码或矛盾的抽象 |

**Fixed point**：上一个阶段 review 的 HEAD。

**流程**：`/code-review` 双轴并行，Spec 轴额外对照迁移计划阶段验收标准。

## Review 日历

```
阶段 0+1+2（已完成）
  R1: #2 #3 #4 阶段 review ✅

阶段 3: 简历模块
  #5 完成 -> 单 issue review ✅
  #6 完成 -> 单 issue review ✅
  R2: #5 #6 阶段 review ✅

阶段 4: 文字面试（P0 核心）
  #7 完成 -> 单 issue review ✅
  #8 完成 -> 单 issue review ✅
  #9 完成 -> 单 issue review ✅
  R3: #7 #8 #9 阶段 review（创建->出题->答题->评估->报告闭环） ✅

阶段 5: 知识库+RAG
  #10 完成 -> 单 issue review ✅
  #11 完成 -> 单 issue review ✅
  R4: #10 #11 阶段 review（上传->向量化->RAG 流式问答闭环） ✅

阶段 6: 供应商+日程
  #12 完成 -> 单 issue review ✅
  #13 完成 -> 单 issue review ✅
  R5: #12 #13 阶段 review

阶段 7: 语音面试（最复杂）
  #14 完成 -> 单 issue review
  R6: #14 阶段 review（REST 生命周期，WS 前置检查点）
  #15 完成 -> 单 issue review
  #16 完成 -> 单 issue review
  #17 完成 -> 单 issue review
  R7: #15 #16 #17 阶段 review（WS 实时管线闭环）

阶段 8: 收尾
  #18 完成 -> 单 issue review
  R8: #18 阶段 review（全系统最终 review）
```

## 统计

| 类型 | 次数 | 触发条件 |
|------|------|---------|
| 单 issue review | 14 次（#5-#18） | 每个 issue make verify 通过后 |
| 阶段 review | 7 次（R2-R8） | 阶段内所有 issue + 单 issue review 完成后 |
| 合计 | 21 次 | |

## 设计说明

**按迁移阶段切分阶段 review**：每个阶段是一个完整业务闭环。单 issue review 会割裂上下文（如 #5 上传 + #6 分析是一个闭环），阶段 review 补全跨 issue 视角。

**R6 中间检查点**：阶段 7（语音面试）4 个 issue 8-12 天，是全项目最复杂部分。#14（REST 生命周期）是 #15-#17（WebSocket）的前置依赖，先 review #14 确保 REST 层和状态机正确，防止问题传导到 WS 层。

**每次 review 的 fixed point**：上一次 review 结束时的 commit，确保只审查新增改动。

## 执行模板

每个 review 按 `/code-review` 流程：

1. `git diff <上次review的HEAD>...HEAD`（三 dot diff）
2. 识别 spec 来源（对应 issue body + 迁移计划阶段描述）
3. 识别 standards 来源（AGENTS.md + ADR + pyproject.toml）
4. 双轴并行子代理（Standards + Spec）
5. 聚合报告，按严重度排序
6. 修复 -> commit -> push
