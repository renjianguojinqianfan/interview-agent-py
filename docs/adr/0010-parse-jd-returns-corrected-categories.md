# parse-jd 返回纠正后分类而非 LLM 原始输出

技能管理（issue #7）的 parse-jd 接口返回经域服务清洗与纠正的 categories：`sanitize_category_key`/`sanitize_category_label` 规范化 LLM 输出，`categoryRefIndex` 将 ref/shared 覆盖为本地权威映射。Java 参考实现（`InterviewSkillService.parseJd`）返回 LLM 原始 categories，纠正逻辑（`buildCustomSkill`）推迟到出题流程调用。我们选择在 parse-jd 即纠正，理由：①符合 issue"结构化技能分类与匹配方向"语义，客户端拿到干净可用结果；②#7 端到端验证域服务纠正逻辑，而非仅靠单元测试；③避免 raw LLM 输出（可能含非法 key、幻觉 ref）直达客户端。代价是 parse-jd 与 Java 行为不一致，后续若需"查看 LLM 原始提取"须另设接口。技能模块分层（纯算法进 `domain/services/skill_service.py`，LLM 编排进 `application/skill/service.py`）是 AGENTS.md §4 与 F1 fitness 测试的合规应用，非新决策。

**Considered Options**: 返回原始 categories（对齐 Java）/ 返回纠正后 categories（选定）。原始方案与 Java 1:1 但 raw 输出直达客户端、#7 不端到端验证域服务；纠正方案输出干净、端到端覆盖，偏离 Java 但语义更贴合 issue。
