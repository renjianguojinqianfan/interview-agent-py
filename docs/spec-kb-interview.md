## Problem Statement

Java 参考实现（Snailclimb/interview-guide，基线 `8c80a19` → 目标 `646b23e`）新增了完整的「知识库面试」功能域：用户上传知识库文档后，可让 AI 基于知识库内容异步生成一套结构化面试题库（含参考答案、评分要点、追问池），再从题库组卷进行模拟面试，评估时优先采用题库参考答案。Python 迁移版对该功能域零实现——数据库无题库表、后端无对应端点、前端无相关页面，用户无法在 Python 版使用知识库面试。同时既有文字面试的会话/题目 DTO 契约落后于 Java 新版（缺 sourceType / knowledgeBaseId / interviewCategory / referenceAnswer 等字段）。

## Solution

将 Java `8c80a19..646b23e` 的知识库面试功能域完整迁移到 Python 版：新增题库数据模型与迁移、题目 CRUD 与筛选端点、基于 Redis Stream 的异步题目生成（含状态机、原子领取、恢复调度双保险）、题库组卷面试（严格容量校验 + 容量预检）、评估上下文改造（题库参考答案优先），并把 Java 前端新增页面整文件搬入（已验证 Python 前端与 Java 基线零实质漂移）。前端零自主改动，后端契约以前端调用为权威。

## User Stories

1. 作为用户，我想在知识库列表页看到每个知识库的题目生成状态（questionGenStatus/questionGenError），以便了解题库是否就绪
2. 作为用户，我想对已完成向量化的知识库提交「生成题库」任务并指定难度/题量/追问数/方向数，以便让 AI 基于我的资料出题
3. 作为用户，我想在生成过程中轮询看到 QUEUED/PROCESSING/COMPLETED/FAILED 状态与结果消息（已生成 N 道、跳过 M 道重复），以便掌握进度
4. 作为用户，我想在生成进行中重复提交时被拒绝（明确报错），以免任务串扰
5. 作为用户，我想在知识库尚未完成向量化时提交生成被拒绝，以免生成空题库
6. 作为用户，我想让生成结果整体替换旧题库（同一事务内），以免新旧题目混杂
7. 作为用户，我想在后台服务崩溃后生成任务被自动恢复（QUEUED 卡 2 分钟重投、PROCESSING 卡 20 分钟重置重投），以免任务永久卡死
8. 作为用户，我想浏览某知识库的题目列表并按状态/方向/难度/关键词筛选，以便管理题库
9. 作为用户，我想查看某知识库的方向（category）及各方向题目数统计，以便选择面试方向
10. 作为用户，我想手动新增题目到题库，以便补充 AI 未覆盖的考点
11. 作为用户，我想编辑题目的题干/参考答案/要点/评分规则/追问，以便修正 AI 生成内容
12. 作为用户，我想将题目在 DRAFT/ACTIVE 间切换（上下架），以便控制哪些题目参与组卷
13. 作为用户，我想删除不需要的题目，以便保持题库整洁
14. 作为用户，我想在开始知识库面试前预检容量（各方向可用题数 + 0~5 追问档位可行性矩阵），以便配置可行的面试参数
15. 作为用户，我想指定知识库/方向/难度/主问题数/每题追问数创建面试会话，系统从 ACTIVE 题目随机抽卷（主题洗牌 + 追问 Fisher-Yates 随机抽取），以便每次面试题目组合不同
16. 作为用户，我想在候选题不足时（主问题数不够或追问池不足）收到明确的拒绝消息（含方向/难度/追问约束明细），以便调整参数
17. 作为用户，我想知识库面试沿用既有文字面试的答题/保存/完成流程（复用同一会话体系，skillId 固定 knowledge-base，sourceType=KNOWLEDGE_BASE），以便体验一致
18. 作为用户，我想面试评估时优先采用题库自带的参考答案/评分要点/评分规则作为评分上下文（为空回落 Skill 参考），以便评分更贴合我的资料
19. 作为用户，我想评估报告中的参考答案用题库标准答案覆盖 LLM 生成的，以便报告权威可信
20. 作为用户，我想在面试记录列表看到会话的 sourceType/knowledgeBaseId/interviewCategory，以便区分普通面试与知识库面试
21. 作为用户，我想按知识库过滤面试记录并从记录页返回题库页，以便管理某知识库的面试历史
22. 作为用户，我想通过 GET /api/knowledgebase/{id} 获取单个知识库详情（题库管理页头部信息），以便页面正常加载
23. 作为用户，我想普通（简历/技能）面试行为完全不变（新字段为 null/NORMAL），以免迁移引入回归
24. 作为开发者，我想异步消费者具备原子领取语义（QUEUED→PROCESSING 行锁 + taskId 匹配，失败静默 ACK 丢弃），以防重复消费与旧任务串扰
25. 作为开发者，我想生成任务的 LLM 调用不在数据库事务内，以免长事务锁表
26. 作为开发者，我想题干归一化去重（NFC + 小写 + 仅字母数字），跳过的重复题计入 skippedCount，以保证题库质量

## Implementation Decisions

（以下决策经 2026-07-25 grilling 会话逐项确认，Java 语义为准、本仓库规约优先）

- **范围**：迁移功能域本体 + 既有文字面试契约扩展；Java 工程杂项（Flyway 基线、commit-msg hook）不迁移，`tryMarkProcessing` 基类钩子按需吸收
- **数据库（单迁移 012）**：`knowledge_base_questions` 新表（题干/方向/难度/type/topicSummary/referenceAnswer/keyPointsJson/scoringRubric/followUpsJson/sourceContext/kbContentHash/status DRAFT|ACTIVE，索引 kb+status、skill+difficulty）；`knowledge_bases` 加 8 列（question_gen_status NONE|QUEUED|PROCESSING|COMPLETED|FAILED + CHECK 约束、task_id、config、error、message、saved_count、skipped_count、updated_at + 状态索引）；`interview_sessions` 加 3 列（source_type 默认 NORMAL、knowledge_base_id、interview_category）。时间列一律 timestamptz（ADR-0013 口径，不照搬 Java naive TIMESTAMP(6)）
- **API 契约**（对齐 Java Controller 与前端 knowledgebase.ts，Result 包裹）：题目列表/方向计数/生成提交（限流 2/s global+ip）/生成状态轮询/题目新增、更新、状态切换、删除；`POST /api/knowledgebase-interviews/sessions` 创建组卷面试（返回 InterviewSessionDTO 含 knowledgeBaseId/interviewCategory）；`GET /api/knowledgebase/{id}/interview-capacity`（mainQuestionCount 1~20 校验）；补实现 `GET /api/knowledgebase/{id}`（前端题库页调用，从 ADR-0015 死端点清单移出）
- **DTO 扩展**：InterviewQuestionDTO 加 referenceAnswer/keyPoints/scoringRubric/sourceContext（完全照搬下发，不脱敏不裁剪）；SessionListItemDTO 加 sourceType/knowledgeBaseId/interviewCategory；InterviewDetailDTO 加 sourceType/knowledgeBaseId；InterviewSessionDTO 加 knowledgeBaseId/interviewCategory；KnowledgeBaseListItemDTO 加 questionGenStatus/questionGenError；camelCase 序列化沿用现有 BaseSchema
- **分层落位**：组卷/容量算法（严格容量校验、洗牌抽题、Fisher-Yates 追问抽取、容量档位矩阵、题干归一化去重）下沉 domain/services 纯函数，随机源以 random.Random 注入；评估上下文构建（题库参考优先、回落 Skill）与报告参考答案合并同样为 domain 纯函数；应用服务留在 application/knowledgebase 域（question/generation/interview 三个 service）；新端点集中在新路由文件，GET /{id} 补进现有 knowledgebase 路由
- **异步生成**：复用 BaseStreamProducer/BaseStreamConsumer 新增 question_gen 任务对；基类新增可选钩子 try_mark_processing(payload)->bool（默认返回 True 并调用现有 mark_processing，存量 4 消费者零改动），生成消费者以 SELECT FOR UPDATE + taskId 校验实现原子领取，领取失败静默 ACK；scheduler 新增恢复 job（每 60s：QUEUED 逾 2min 重投、PROCESSING 逾 20min 重置回 QUEUED 再投），与 xautoclaim 双保险；失败对外统一安全文案「题目生成失败，请稍后重试」
- **LLM 生成**：复用 StructuredOutputInvoker + Pydantic 输出模型；2 个 .st 提示词模板照搬 Java（system+user，注入已有方向 Top10、已有题目 Top20、难度/题量/追问数/方向数、知识库上下文含数据边界指令与净化包裹）；检索上下文用现有 pgvector 检索：4 组固定查询词、每词 top4、去重累积至 top12、5000 字截断；检索为空时报「知识库未检索到可用于生成题目的内容」
- **组卷语义**：候选 = 该知识库 ACTIVE + 难度匹配（方向可选）且追问池 ≥ followUpCount 的题；候选 < mainQuestionCount 时报 INTERVIEW_QUESTION_INSUFFICIENT 含明细文案；主题带 isFollowUp=false，追问题带 isFollowUp=true + parentQuestionIndex；type 空缺回落 KNOWLEDGE_BASE，category 空缺回落「知识库/知识库追问」；会话创建复用既有持久化 + Redis 会话缓存（缓存补存 knowledgeBaseId/interviewCategory）
- **前端**：Java `646b23e` 的 7 个改动文件整文件覆盖 + 约 15 个新文件（3 页面、5 组件、常量/工具模块、6 个 vitest 纯逻辑单测）原样拷入；package.json 依赖差异核对后经确认安装；已验证 Python 前端与 Java 基线零实质漂移，覆盖安全

## Testing Decisions

- 好测试只断言外部行为：API 响应契约、数据库落库结果、状态机可观测状态，不断言内部实现
- domain 纯函数单测（镜像 tests/domain/ 现有风格）：容量矩阵、严格抽取、洗牌注入固定种子、题干去重归一化、评估上下文构建与回落、报告参考答案合并；普通面试回归（无题库参考时行为不变）
- API 契约测试（镜像 tests/api/ 现有 mock 风格）：11 个端点的成功/校验失败/404/重复提交分支
- integration 真库竖切两条（tests/integration/，CI 必跑、本地无 docker 优雅 skip，mock LLM）：① 异步生成全链路（提交→原子领取→mock LLM→替换落库→COMPLETED→轮询可见）+ 旧 taskId 串扰丢弃用例；② 组卷面试全链路（插题→capacity→创建（含容量不足分支）→答题→complete→评估采用题库参考答案）
- 迁移链测试沿用 tests/test_migration_chain.py 模式覆盖 012；架构守卫（test_architecture.py）覆盖新路由的端点覆盖率与分层依赖
- 前端行为测试直接使用搬入的 Java vitest 单测；验收 = make verify 双栈全绿 + 新页面浏览器冒烟 0 致命 console error

## Out of Scope

- Java 侧开放未合并 PR（#43 Atlas provider、#39 限流原子性等）——未进 master 不迁移
- Java 工程杂项：Flyway V1 基线、.githooks/commit-msg、README 更新
- 其余 ADR-0015 死端点（/query、/query/stream、/uncategorized、面试 /report、RAG /{id}/knowledge-bases、简历 /health）——Java 新版前端仍无调用，维持不实现
- sourceContext 下发体积优化、参考答案脱敏——Java 生产行为如此，不做提前优化
- 语音面试、RAG 聊天等其他模块的任何改动

## Further Notes

- 基线可靠性：本地 java-reference reflog 确认 `8c80a19`（2026-07-10 克隆）→ `646b23e`（2026-07-25 pull），且 646b23e == origin/master 最新，无遗漏
- 实施拆 5 票（依赖链 1→2→3→4→5）：①schema 基座（迁移 012+ORM）②题库 CRUD（含 GET /{id} + 列表 DTO 扩展）③异步生成（状态机+任务对+恢复 job+模板+2 端点）④组卷面试+契约扩展+评估改造 ⑤前端搬运+双栈 verify+冒烟
- 文档同步（各票 neat-freak 分摊）：新增 ADR-0017（单迁移、timestamptz 口径、try_mark_processing 钩子、恢复 job 双保险、GET /{id} 转活）；ADR-0015 死端点清单移出 GET /{id}；CONTEXT.md 补术语（题库、组卷、方向、生成状态机、追问池）；docs/api.md 补 11 端点；docs/migration-plan.md 记入本轮 Java 增量
- Java 侧三份 TDD 笔记（.agents/tdd/knowledge-base-*.tdd.md）是容量边界、完成流程、异步可靠性的权威场景清单，实现票 ③④ 时应对照
