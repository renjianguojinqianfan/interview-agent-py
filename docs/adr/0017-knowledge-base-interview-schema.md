# ADR-0017: 知识库面试功能域 schema 与迁移决策

- 状态：已接受
- 日期：2026-07-26
- 关联：issue #40（spec）、#41（schema 基座）、ADR-0002（追加式迁移）、ADR-0013（timezone-aware）

## 背景

Java 参考实现（`8c80a19..646b23e`）新增「知识库面试」功能域：AI 基于知识库内容异步生成题库，
再从题库组卷面试。Python 迁移版需要新增题库表、知识库生成状态列族、会话来源标注列，
并在若干处 Java 语义与本仓库既有规约冲突时做出取舍（Java 语义为准、本仓库规约优先）。

## 决策

### 1. 单迁移 012 三块合一

`knowledge_base_questions` 新表、`knowledge_bases` 8 个 `question_gen_*` 列、
`interview_sessions` 3 个来源列在同一个迁移 012 内交付，而非拆成三个迁移。
三块同属一个功能域地基、无独立回滚场景，单迁移保持往返（upgrade/downgrade）原子。

### 2. 时间列 timestamptz 口径

Java 侧照搬会引入 naive `TIMESTAMP(6)`（`created_at`/`updated_at`/`question_gen_updated_at`）。
按 ADR-0013 post-010 约定，新增 datetime 列一律 `DateTime(timezone=True)`（timestamptz），
不照搬 Java naive。

### 3. 题库外键 ON DELETE CASCADE（偏离 Java）

Java 的 `knowledge_base_questions.knowledge_base_id` 外键为默认 RESTRICT，且其删除服务
（`KnowledgeBaseDeleteService`）未清理题目——删除带题库的知识库会直接外键报错，属 Java 侧缺陷。
Python 版沿用本仓库 `interview_answers` 的 CASCADE 惯例：删知识库级联删题目，无孤儿题。
`interview_sessions.knowledge_base_id` 则照搬 Java 裸列（无外键）：删知识库后面试会话保留历史可查。

### 4. 题目状态 CHECK 保留 Java 枚举全集

`knowledge_base_questions.status` 的 CHECK 约束为 `DRAFT/ACTIVE/ARCHIVED/STALE`
（Java `KnowledgeBaseQuestionStatus` 全集），尽管业务当前只使用 DRAFT/ACTIVE（上下架）。
收窄约束属对 Java 语义的提前优化，后续 Java 若启用 ARCHIVED/STALE 会造成迁移分叉。

### 5. 迁移往返测试入 integration

结构守卫（`tests/test_migration_chain.py`）只校验链形态；012 起新增真库往返测试
（`tests/integration/test_migration_roundtrip.py`）：`upgrade head -> downgrade 011 -> upgrade head`
并断言 schema 事实，与集成竖切同惯例（CI 必跑、本地无 docker 优雅 skip）。

### 6. try_mark_processing 可选钩子（#43）

`BaseStreamConsumer` 新增 `try_mark_processing(payload) -> bool` 可选钩子：默认实现调用
既有 `mark_processing` 并返回 True（存量 4 消费者零改动）；题库生成消费者覆写为
行锁（SELECT FOR UPDATE）+ taskId 匹配的原子领取（QUEUED -> PROCESSING），
领取失败静默 ACK 丢弃——旧任务消息不串扰、不重试、不标失败。

### 7. 生成任务恢复 job 与 xautoclaim 双保险（#43）

除 Stream 自带的 xautoclaim pending 回收外，新增每 60s 调度 job：QUEUED 逾 2 分钟
（消息丢失/入队未达）刷新时间戳后重投；PROCESSING 逾 20 分钟（执行节点崩溃）重置回
QUEUED 再重投。重投携原 taskId，由消费侧原子领取去重；LLM 调用始终在事务外，
替换旧题 + 置 COMPLETED 在同一小事务。

### 8. INTERVIEW_QUESTION_INSUFFICIENT 用 3012（偏离 Java 3009）

Java 组卷候选不足报 3009，但本仓库 3009/3010 已被 SKILL_NOT_FOUND/JD_PARSE_FAILED
占用（先于 Java 新增），改用 3012。前端对该错误不按码分支、仅展示 message，属安全偏离；
不足明细消息（方向/难度/追问约束）与 Java 逐字对齐。

### 9. 组卷/评估参考的 domain 纯函数与回落口径（#44）

组卷（主题洗牌 + Fisher-Yates 追问抽取）、容量矩阵与评估参考构建均为
`domain/services/question_bank` 纯函数，随机源（`random.Random`）注入、固定种子可复现。
评估时题库参考优先（拼入评估上下文 + 报告 referenceAnswers 用题库标准答案覆盖）；
无题库参考时回落维持 Python 现状空参考（偏离 Java 的 Skill 参考回落——Python 评估
消费者从未接入 Skill 评估参考，普通面试行为严格不变并有回归测试）。
消费者基类以 `_build_reference_context` 可选钩子接入（默认 None，语音消费者零改动）。

## 后续（随实现票追加）

- ~~try_mark_processing 消费者钩子（#43）~~ 已落地（#43，2026-07-26，见决策 6）
- ~~生成任务恢复 job 与 xautoclaim 双保险（#43）~~ 已落地（#43，2026-07-26，见决策 7）
- ~~GET /api/knowledgebase/{id} 从 ADR-0015 死端点清单转活（#42）~~ 已落地（#42，2026-07-26）
- ~~组卷面试与评估改造（#44）~~ 已落地（#44，2026-07-26，见决策 8/9）

## 影响

- 数据库新增 1 表 + 11 列 + 3 索引 + 2 CHECK 约束，存量行为零回归（新列均有默认值）
- ORM：`KnowledgeBaseQuestion` 新模型、`KnowledgeBase`/`InterviewSession` 补列，
  `updated_at` 由 ORM `onupdate` 维护（Java `@UpdateTimestamp` 语义）
