# 测试策略：从分层金字塔转向行为奖杯 + 契约一致性机械守卫

行为覆盖审计（以前端用户动作为主轴逐条核对"点按钮 → 落什么数据 / 触发什么行为 → 哪层测试守护"）发现：现有上百个后端测试按 DDD 分层镜像组织（`tests/api`／`tests/application`／`tests/domain`／`tests/infrastructure`），每层 mock 掉相邻层——api 测真路由但 mock 服务、application mock 仓储、infrastructure mock session。后果是：**没有任何一个测试跑过 `真 HTTP → 真服务 → 真库` 的完整竖切**；4 条真库 e2e 全部从服务/消费者/定时任务起步、绕过 HTTP 层，且因 `.github/workflows/ci.yml` 未挂 postgres/redis service 而被 `backend/tests/e2e/conftest.py` 自动 skip（在 CI 中等于不跑）；前端 13 个页面零自动化测试，仅 eslint+tsc 兜底。病灶是**测试按代码结构组织、而非按用户行为与契约组织，且每条缝都用 mock，故缝从不被验证**——测试数量高、行为可信度低（上百测试对 ADR-0015 已记录的 7 处前端死端点声明零报警能力即为证）。

ADR-0001 定「前端为权威契约、后端对齐」，ADR-0015 据此**一次性、手工**（逐页浏览器冒烟 + 手改）把契约对齐并显式记录 7 处死端点"不实现"。本 ADR 解决其遗留的系统性问题：**如何让契约永远保持对齐、漂移不再悄悄堆积，以及如何让测试守住"按钮 → 数据"这条链**。

我们决定：**测试重心从"分层镜像金字塔"转向"以用户动作为单位的行为奖杯"；两条要紧的缝（HTTP 契约、前后端类型契约）用机械 fitness 守卫锁死；真库集成测试成为 CI 默认必跑。**

- **奖杯分层**：domain 纯算法（评估／出题／解析）保留快速单测——它们值。新增"竖切集成测试"为主体：`TestClient`/httpx + 真 Postgres/Redis + 只假 AI（LLM/ASR/TTS），按功能域（非分层）组织于 `tests/integration/`，每个"有副作用的用户动作"至少一条竖切，断言"请求 → 落库/副作用 → 响应形状"。顶层保留**极薄** Playwright happy-path e2e（2~3 条关键旅程）。
- **拆掉"逼你 mock"的枷锁**：CI 增加 postgres+redis service（GitHub Actions `services:`），集成/e2e 从"无基础设施 auto-skip"改为 **CI 必跑**（缺基础设施则 fail 而非 skip）；沿用现有 `backend/tests/e2e/conftest.py` 的 per-test TRUNCATE 隔离（已验证稳定），不引入事务回滚复杂度；本地无 docker 仍优雅 skip，开发体验不退化。
- **契约一致性守卫（尊重 ADR-0001 前端权威、零改动）**：新增 fitness 测试（落 `tests/test_architecture.py` 同源守卫位），扫描 `frontend/src/api/*.ts` 声明的 `(method, path)`，断言每个都能匹配 FastAPI 运行时导出的 OpenAPI schema 路由；ADR-0015 已知的 7 处死声明登记进显式白名单——把"散落的隐性约定"升级为"机器校验的登记表"，**新**漂移即报警。方向单一：`前端调用 ⊆ 后端 schema` 的子集校验，**不做后端 → 前端 codegen**（那会改写前端、违背 ADR-0001）。字段/类型层面的形状漂移由竖切集成测试（真实响应体）覆盖，不追求纯静态全量比对。
- **前端行为门禁**：引入 vitest + @testing-library + MSW（handler 手写、由契约守卫间接保真）；`make verify` 前端段与 CI 增加前端 test 步；先覆盖高风险巨页（Settings 1500 行 / Voice 937 行）的按钮交互——发对请求 → 改对状态 → 渲染对结果。
- **度量换轨**：不再以行覆盖率为主目标，改 track "行为覆盖率" = 有竖切守护的有副作用动作数 / 总数；审计矩阵作为记分牌落库。新增 fitness 守卫：每个有副作用的 router 端点（写/触发类）至少一条竖切（只读/导出类白名单豁免）。

**不变量**：前端零改动、前端为权威契约（ADR-0001/0015）不变——守卫只做单向子集校验 + 死声明白名单，不生成/改写前端。追加式迁移（ADR-0002）、内部 aware UTC 时钟纪律（ADR-0013）、显式 commit 后 send（ADR-0008）不受影响，竖切测试反而成为这些不变量在真库下的回归载体。`make verify` 双栈全绿仍是 DoD；新增真库集成在 CI 必跑、本地无 docker 优雅 skip。既有单测不批量删除，仅在竖切覆盖同一行为后、增量下线重复的中间层 mock 测试（原子提交）。

**Considered Options**：
- 继续加分层单测冲行覆盖率——**否**：数量↑而行为可信度不变，正是本 ADR 要消除的病灶。
- 后端 OpenAPI → 前端 TS 类型/client 代码生成（单一来源）——**否**：会改写前端，违背 ADR-0001「前端为权威、零改动」；单向契约守卫已达同等防漂移效果。
- testcontainers 起临时 PG/Redis——**否（暂）**：新增依赖 + Docker-in-CI 开销；现有 `docker-compose.yml` + CI service 已够，需本地 hermetic 时再引入。
- 事务回滚 fixture 替代 TRUNCATE——**否**：与 async 每测试独立 engine（避免事件循环复用）模式冲突，现有 per-test TRUNCATE 已验证。
- 全量 Playwright 浏览器 e2e——**否**：慢且脆，仅保极薄 happy-path。

**Consequences**：CI 时长增加（起 PG/Redis + 前端 test + 竖切），换取"按钮 → 数据"链路的真实回归防护；需维护契约白名单与行为覆盖矩阵，由 fitness 守卫防腐化；AI 外部服务在竖切中仍假化（无法真调 Qwen），"真 LLM 行为"不在自动化范围，靠人工/评估集单独保障。
