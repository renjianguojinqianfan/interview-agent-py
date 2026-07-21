# 基础设施消费者对应用服务的依赖

评估/分析类 Stream 消费者位于 `infrastructure/tasks/`，作为异步任务的宿主/驱动，天然需要调用业务编排逻辑。我们决定：允许此类宿主消费者导入 application service（如 `resume_analyze_consumer` 导入 `ResumeAnalysisService`），这是消费者作为"驱动方"调用应用服务的常见模式，不视为 AGENTS.md §4 分层违规。

但边界收紧：只有 **application service** 可被 infrastructure 反向导入；纯编解码器/适配器（如 `question_codec`、`voice_qa_adapter`）不携带编排职责，必须置于 `domain/services/`，由 infrastructure 经 domain 导入。issue #19 将 `question_codec` 从 application 迁回 domain 即遵循此界。

机械执行：`tests/test_architecture.py::test_infrastructure_imports_application_only_via_allowlist` 维护 `INFRA_TO_APPLICATION_ALLOWLIST` 白名单；新增 infra→application 导入若非白名单内的 service，即测试失败，倒逼显式决策（pure codec/adapter 应改置 domain，宿主消费者调 service 需登记白名单）。

**Considered Options**: 一律禁止 infra→application（会误伤合法宿主消费者调 service）/ 一律放行（放任 pure codec 反向依赖复发）/ 白名单棘轮（选定）——精确区分"宿主调 service"与"pure codec 反向依赖"，兼顾合法模式与复发防护。
