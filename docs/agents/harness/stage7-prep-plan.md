# Stage 7 准备计划：harness 加固 + R6 检查点

> #14（语音面试 REST 生命周期）已完成推送。进 #15（WebSocket，最复杂）前，按 review-plan.md 编排需先做 R6 阶段 review（#14 检查点）。又 harness plan 的 sprint-aligned 节奏自 Stage 4 起滞后 8 issue，且 #14 规划时人工捕获了 issue body 与 ADR-0008 的矛盾（无机械守卫）。按 "keep quality left" 原则，先 sharpen harness 再跑 R6。

**顺序**：harness 批次（H1/H2/H3）-> R6 -> #15。

**已确认决定**：
- 1-A：harness 先于 R6（sharpen sensors before using them）
- 2-A：H2/H3 全跑 `/code-review`（F5 blast radius 高，误报阻塞所有未来 commit）
- 3-A：F16（BaseSchema 迁出 + application->api 分层守卫）列为后续单独项

---

## 计划 1：harness 加固批次

3 个原子提交，全部文档/测试。F16 不并入（决定 3-A）。

### H1 - F12 GC loop 规则（15min，文档）

- **文件**：`AGENTS.md` §9 技能执行纪律，追加一条
- **内容**：「复审后若发现 HARD 违反，必须新增一个结构测试或 lint 规则防止同类违规复发；纯 finding 响应式小修无需新增规则」
- **依据**：harness plan F12，时机原定「Stage 4 R3 review 发现第一个 HARD 违反后」，已逾期；#15-#17（WS，最复杂）几乎必然在 review 暴露 HARD 违反，此规则是防复发的闸门
- **review**：豁免（纯文档）
- **commit**：`docs(agents): §9 补充 GC loop 规则`

### H2 - F1 扩展：ADR-0008 一致性检查（30min，测试）

- **文件**：`tests/test_architecture.py` 扩展，新增 `test_no_sqlalchemy_after_commit_events`
- **规则**：ast 扫描 `app/**/*.py`，断言无 `event.listens_for(...)` 调用、无 `after_commit` 事件注册。报错：`"ADR-0008 禁止 SQLAlchemy after_commit 事件，应用显式顺序（commit 后 send）- {file}:{line}"`
- **已验证**：app/ 中 0 处 `after_commit`/`listens_for`，立即绿灯
- **范围限定**：只守 ADR-0008。application->api 分层守卫列为 F16 后续项（需先迁 BaseSchema 出 `app/api/`，8 文件 + 设计决策，决定 3-A）
- **review**：`/code-review`（决定 2-A）
- **commit**：`test(architecture): 扩展 fitness 测试覆盖 ADR-0008`

### H3 - F5 文档漂移检测（1h，测试）

- **文件**：`tests/test_doc_drift.py`（新建）
- **规则**：扫描 `docs/**/*.md` 反引号包裹的字符串，过滤出文件路径（须**同时**含 `/` 且以已知扩展名结尾--AND 逻辑，比 plan.md 原 OR 更精确，避免裸文件名误报），多解析基（repo 根/app//docs//tests//文档目录）断言存在
- **KNOWN_MISSING 白名单**：已登记的计划未建文件（voice/asr.py、entities/、harness F2/F3/F6/F13 等）与历史记录引用（pitfalls.md 描述已删/重命名文件）。文件创建后移除以使守卫重新生效
- **风险**：可能首次失败（暴露已有死引用）-> 先修死引用再提交。实际修了 2 处真实漂移（migration-plan.md 的 kb_vectorize.py/resume_analyze.py -> _consumer.py），余 14 条入白名单
- **review**：`/code-review`（决定 2-A，blast radius 高：误报会阻塞所有未来 commit 的 pre-commit hook）
- **commit**：`test(docs): 新增文档漂移检测测试`

### 执行顺序与闸门

1. 写 H1（AGENTS.md）+ H2（test_architecture 扩展）+ H3（test_doc_drift）
2. `make verify` -> 若 H3 失败，修死引用，直到全绿
3. `/code-review` 审 H2+H3 的 tests/ diff（Standards + Spec 双轴）
4. 修复 review findings
5. 3 个原子提交：H1（doc 豁免）-> H2 -> H3

---

## 计划 2：R6 阶段 review（#14 检查点）

- **技能**：`/code-review`
- **fixed point**：`114b7f2`（R5 的 HEAD，依 review-plan.md line 99 "上次 review 的 HEAD"）
- **diff 范围**：`114b7f2...HEAD` = #14 的 3 commit + harness 批次的 3 commit
- **焦点**：#14 的代码（harness commit 已在 H2/H3 各自 review 过，R6 Spec 轴聚焦 #14，Standards 轴对 harness 测试放行）
- **Spec 源**：issue #14 body + migration-plan §7A（7A.1-7A.6）
- **镜头（阶段 review 第二层，区别于已完成的单 issue review）**：
  - 跨 issue 集成就绪度：#14 对 #15-#17 WS 的前置契合（状态机能否驱动 WS 事件、会话缓存能否支持 WS 握手、评估复用衔接）
  - 迁移计划 7A 验收标准逐条对照
  - 架构一致性：voice 模块 DDD 分层与 interview/schedule/rag 模块统一
  - 重复/冲突：voice 评估消费者与文字评估消费者是否有可提取共享抽象
- **Standards 源**：AGENTS.md（含新增 F12 GC loop）+ ADR-0008（含新增 H2 守卫）+ pyproject.toml
- **双轴**：Standards + Spec 并行子代理
- **HARD 违反处置**：若发现，触发 F12 GC loop（加防复发测试）-> 修复 -> 增量复审
- **通过后**：commit findings 修复（如有）-> 进 #15

---

## 自检

| 检查项 | 状态 |
|---|---|
| H1/H2/H3 文件路径明确 | ✓ AGENTS.md / test_architecture.py / test_doc_drift.py |
| H2 规则已验证 0 现存违规 | ✓ app/ 无 after_commit/listens_for |
| H3 死引用风险已识别 | ✓ 计划含「先修死引用」步骤 |
| R6 fixed point 正确 | ✓ 114b7f2 = R5 HEAD（review-plan line 99） |
| R6 与单 issue review 镜头区分 | ✓ 阶段层（集成/架构/重复）vs issue 层（acceptance） |
| harness 批次 review 覆盖 | ✓ H2/H3 跑 /code-review（2-A），H1 豁免 |
| F16 边界清晰 | ✓ 仅 ADR-0008，分层守卫拆出 |
| 顺序自洽 | ✓ harness 先 -> R6 用新守卫 -> HARD finding 触发 F12 |
| commit message 符合 §8 格式 | ✓ type(scope): 中文 subject |

**待留意**：R6 diff 含 harness commit，Standards 子代理会看到 H2/H3 测试代码（已 review）。需在 Spec 子代理 prompt 里明确「harness 测试非 #14 spec 范围，聚焦 #14 的 10 接口/状态机/评估/定时任务」。

---

## 执行后的文档同步

本批次完成后需更新：
- `docs/agents/harness/plan.md`：F5/F12 标记 ✅，F1 标注「已扩展覆盖 ADR-0008」，新增 F16 条目（BaseSchema 迁出 + 分层守卫，后续）
- `docs/agents/review-plan.md`：R6 完成后标记 ✅
