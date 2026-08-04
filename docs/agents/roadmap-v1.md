# 0.9.0 → 1.0.0 实施路线图

> 基于 2026-08-02 生产化缺口分析报告，经代码库实地验证修订。
> 当前分支：`trae`，所有开发在本分支完成，通过 PR 合并到 `main`。

## 验证说明

报告原文经代码库逐条核对，以下修正项已嵌入本计划：

| # | 报告原文 | 修正 | 依据 |
|---|---------|------|------|
| 1 | P0-1"第 1 行注释" | 第 4 行 docstring | [adaptive_service.py:4](file:///workspace/backend/app/application/agent/adaptive_service.py#L4) |
| 2 | F16"8 个 application 文件导入" | **11 个** | [Grep 结果](file:///workspace/backend/app/application/) 除 `agentic_rag_service.py` 外 11 个 schemas.py 均导入 BaseSchema |
| 3 | P2"尚未完成的 6 项" | 实际 **9 项**（F2/F6/F7/F8/F9/F10/F11/F13/F16） | [harness/plan.md](harness/plan.md) 全文统计 |
| 4 | P1-4"每轮只调一个工具" | 路由层无 Send fan-out，但 `_execute_tool` 串行处理所有 tool_calls | [adaptive_interview.py:259](file:///workspace/backend/app/graphs/adaptive_interview.py#L259) |
| 5 | P1-2 仅依赖 P0-1 | 还依赖 P1-3（streaming）— interrupt 后需前端感知恢复点 |

---

## 版本规划

```
0.9.1  P0-3  @tool 壳改造                              ← 半天，零依赖
0.9.2  P1-5  Agent 决策 trace                           ← 半天，零依赖
0.10.0 P0-1  Checkpointer 持久化                         ← 1-2 天，所有后续功能的前置
0.10.1 P1-3  Streaming 输出                              ← 1 天，依赖 0.10.0
0.11.0 P1-1  Subgraph 聚合（RAG 作为 Agent 工具）       ← 2-3 天
0.11.1 P1-2  Human-in-the-Loop                          ← 1-2 天，依赖 0.10.0 + 0.10.1
0.12.0 P1-4  并行工具调用                                ← 2 天，依赖 0.11.0
       P2    harness 穿插（F7 → F6 → F16）
1.0.0  P0-2  认证模块                                    ← 1-2 天
       P3    按需
```

---

## P0：生产化缺口（1.0.0 前置条件）

### P0-1：Agent 会话状态持久化（0.10.0）

**现状**：[adaptive_service.py:48](file:///workspace/backend/app/application/agent/adaptive_service.py#L48) `OrderedDict` 内存存储 + LRU 淘汰（上限 500），重启即丢。

**为什么必须做**：自适应面试是多轮交互（6-20 轮），中间用户刷新页面或服务重启，整个面试会话消失。

**方案**：LangGraph Checkpointer 机制

```python
# 生产：RedisSaver
from langgraph.checkpoint.redis import RedisSaver

checkpointer = RedisSaver.from_conn_string(settings.redis_url)
self._compiled = self._build().compile(checkpointer=checkpointer)

# 调用时传 thread_id
await self._compiled.ainvoke(
    initial_state,
    config={"configurable": {..., "thread_id": session_id}},
)
```

**改动范围**：
- `adaptive_service.py`：移除 `_sessions` OrderedDict，改用 checkpointer
- `agentic_rag_service.py`：RAG 也可改用 checkpointer（可选）
- `deps.py`：注入 checkpointer 依赖
- `pyproject.toml`：新增 `langgraph-checkpoint-redis` 依赖

**工作量**：1-2 天。

**前置**：确保 `settings.redis_url` 可用（已有 Redis 连接配置）。

---

### P0-2：认证模块（1.0.0）

**现状**：[ADR-0007](../adr/0007-no-auth-optional-user-ratelimit.md) 明确"无认证 + 可选用户标识 + IP 限流"。开发阶段合理，上生产必须有。

**方案**：JWT 最小化实现——不引入 OAuth2 服务端，只做 Bearer token 校验。

```python
POST /api/auth/login   → {username, password} → {access_token}
其他路由 → Depends(verify_token)
```

**关键设计决策**：1.0.0 只做认证不做授权——所有登录用户同等权限，RBAC 留 1.1.0。

**改动范围**：
- 新增 `app/api/routers/auth.py`
- 新增 `app/infrastructure/auth/jwt.py`
- `app/api/deps.py`：加 `get_current_user`
- 其他路由逐步加 `Depends(get_current_user)`
- 新建 ADR-0020 覆盖 ADR-0007 的"无认证"决策

**工作量**：1-2 天。

---

### P0-3：@tool 壳改 StructuredTool.from_schema（0.9.1）

**现状**：[interview_tools.py:154-197](../../backend/app/graphs/tools/interview_tools.py#L154-L197) 4 个 `@tool` 函数返回占位字符串 `"该工具应由 Agent 内部执行"`，误调时静默返回无意义字符串。

**方案**：改用 `StructuredTool.from_schema`，不传 `func` → 直接调用时报错而不是静默返回。

```python
# 改前
@tool
def generate_question(category: str, difficulty: str) -> str:
    """..."""
    return "该工具应由 Agent 内部执行"

# 改后
generate_question_tool = StructuredTool.from_schema(
    name="generate_question",
    description="按指定方向和难度生成一道面试题",
    args_schema=GenerateQuestionArgs,
    # 不传 func → 直接调用会报错
)
```

**改动范围**：
- `interview_tools.py`：4 个 `@tool` 改为 `StructuredTool.from_schema`
- `rag_tools.py`：如有类似 `@tool` 壳也应改
- `adaptive_interview.py`：`bind_tools` 参数类型从 `@tool` 列表变为 `StructuredTool` 列表

**工作量**：半天。

**注意**：`_dispatch_tool` 在 `adaptive_interview.py` 中通过 `tool_call["name"]` 分发到 `_impl` 函数，`@tool` 壳本身不参与实际执行。改变壳类型不影响 `_dispatch_tool` 逻辑。

---

## P1：Agent 能力深化

### ✅ P1-1：LangGraph Subgraph 聚合（0.11.0）

**现状**：三个图（评估图 DAG、ReAct 循环 Agent、RAG 自纠错）各自独立，无组合关系。

**方案**：把 RAG Agent 作为 ReAct Agent 的一个工具。自适应面试 Agent 在需要查参考资料时，调用 Agentic RAG（带质量循环），而不是现在的 `lookup_reference`（只读本地文件）。

```python
adaptive_interview Agent
    ├── generate_question
    ├── evaluate_answer
    ├── agentic_rag_search   ← 嵌入 RAG Agent 作为子图工具
    └── adjust_strategy
```

**技术实现**：LangGraph 的 compiled subgraph 可以作为 tool 被父图调用。或者在 `_execute_tool` 节点里调 `RagAgentGraph().ainvoke()`。

**改动范围**：
- `rag_agent.py`：暴露为可被父图调用的接口
- `adaptive_interview.py`：新增 `agentic_rag_search` 工具 + 注册到 `_dispatch_tool`
- `interview_tools.py`：新增 `agentic_rag_search` 工具

**工作量**：2-3 天。

**学习价值**：LangGraph Multi-Agent / Subgraph 模式。

---

### ✅ P1-2：Human-in-the-Loop（0.11.1）

**现状**：ReAct Agent 完全自动，无人工干预点。`_MAX_AGENT_STEPS=30` 是硬上限。

**前置条件**：
- P0-1（Checkpointer）—— interrupt 后恢复依赖 checkpoint
- P1-3（Streaming）—— 前端需感知恢复点才能展示审批界面

**方案**：在 `evaluate_answer` 工具执行后、`generate_question` 执行前，让面试官（人类）审核题目是否合适。

```python
from langgraph.types import interrupt

async def _execute_tool(state, config):
    if tool_name == "generate_question":
        question = await generate_question_impl(...)
        approval = interrupt({"question": question, "prompt": "这道题合适吗？"})
        if approval == "reject":
            return {"messages": [..., HumanMessage("换一题")]}
```

**改动范围**：
- `adaptive_interview.py`：`_execute_tool` 中加 interrupt 点
- `agent_interview.py`：新增 resume 端点供前端通过 `Command(resume=...)` 恢复
- 前端：新增审批 UI 组件

**工作量**：1-2 天。

---

### ✅ P1-3：Streaming 输出（0.10.1）

**现状**：自适应面试 API 是同步的——`POST /sessions/{id}/answer` → 等 Agent 跑完 → 返回结果。用户看不到 Agent 思考过程。

**前置条件**：P0-1（Checkpointer）—— streaming 结合 checkpoint 才能在断连后恢复。

**方案**：用 LangGraph 的 `astream_events()` 把 Agent 每一步推给前端。

```python
@router.post("/sessions/{id}/answer/stream")
async def submit_answer_stream(session_id, body, service):
    async def event_stream():
        async for event in service.stream_answer(session_id, body.answer):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

事件类型：
- `on_tool_start`：开始调 generate_question
- `on_tool_end`：题目生成完毕
- `on_llm_stream`：LLM 逐 token 输出
- `on_chain_end`：本轮循环结束

**改动范围**：
- `adaptive_service.py`：新增 `stream_answer` 方法
- `agent_interview.py`：新增 stream 端点
- `agentic_rag_service.py`：可选加 streaming

**工作量**：1 天。

---

### ✅ P1-4：并行工具调用（0.12.0）

**现状**：路由层（`_route_agent_output`）不做 `Send` fan-out。LLM 如果返回多个 `tool_calls`，在 `_execute_tool` 中被**串行**顺序处理（[adaptive_interview.py:259](file:///workspace/backend/app/graphs/adaptive_interview.py#L259) `for tool_call in last_msg.tool_calls`）。

**前置条件**：P1-1（Subgraph 聚合）——并行工具调用在 Multi-Agent 场景下更有意义。

**方案**：用 `Send` fan-out 并发执行工具调用。

```python
def _route_agent_output(state):
    tool_calls = last_msg.tool_calls
    if len(tool_calls) > 1:
        return [Send("execute_tool", {"tool_call": tc}) for tc in tool_calls]
    elif tool_calls:
        return "execute_tool"
    return "finalize"
```

**前置条件**：messages 必须改为 `Annotated[list, add_messages]` reducer（当前是手动追加，详见隐患分析）。

**工作量**：2 天（含 reducer 改造 + 测试）。

---

### P1-5：Agent 决策 Trace（0.9.2）

**现状**：RAG Agent 有 `retrieval_trace`（[rag_agent.py:60](file:///workspace/backend/app/graphs/rag_agent.py#L60)），但 `AdaptiveInterviewState` 无 `decision_trace`。Agent 跑完只能看最终结果，不知道中间决策链路。

**方案**：在 `AdaptiveInterviewState` 中新增 `decision_trace` 字段。

```python
class AdaptiveInterviewState(TypedDict, total=False):
    ...
    decision_trace: list[dict[str, Any]]
    # {"step": 1, "action": "generate_question", "args": {...}, "result": {...}, "duration_ms": 120}
```

每个节点执行后 append 一条 trace，最终返回给前端。

**改动范围**：
- `adaptive_interview.py`：`AdaptiveInterviewState` 加 `decision_trace`；`_execute_tool`、`_agent_loop`、`_init_context` 各节点执行后 append trace 记录
- `adaptive_service.py`：`_to_session_dto` 可选暴露 trace

**工作量**：半天。

---

## P2：Harness 待办项

从 [harness/plan.md](harness/plan.md) 中尚未完成的 9 项（报告原文说 6 项，实际 9 项）：

| # | 内容 | 工作量 | 优先级 | 说明 |
|---|------|--------|--------|------|
| ✅ F1 | 架构 fitness 测试 | 已完成 | — | domain 层零框架依赖守卫 |
| F2 | 已拒绝方案清单 `docs/rejected-ideas.md` | 30min | 低 | 文档类，随时做 |
| ✅ F3 | infrastructure→application 依赖 ADR | 已完成 | — | ADR-0012 |
| ✅ F4 | CI 补全 format check | 已完成 | — | ci.yml 已加 |
| ✅ F5 | 文档漂移检测 | 已完成 | — | `test_doc_drift.py` |
| **F6** | 词汇表执行测试 `test_glossary.py` | 1h | **中** | CONTEXT.md `_Avoid_` 词条机械执行，防止命名违规复发 |
| **F7** | 覆盖率阈值 `fail_under` | 15min | **中** | 先跑一次确认基线，设基线-2% |
| **F8** | E2E/集成测试 | 2-3d | 低 | 需 docker-compose + pytest integration 标记，报告 P2 表格遗漏 |
| F9 | per-worktree 隔离 | 待平台支持 | 低 | 报告 P2 表格遗漏 |
| **F10** | 运行时可观测性（结构化日志 + Prometheus） | 3-5d | 低 | 生产部署才需要 |
| F11 | `nul` 文件反复出现 | 30min | 低 | 排查创建源或加 pre-commit 清理，报告 P2 表格遗漏 |
| ✅ F12 | GC loop 规则 | 已完成 | — | AGENTS.md §9 |
| F13 | harness 质量度量 `harness-coverage.md` | 30min | 低 | 跟踪规则数/机械执行数 |
| ✅ F14 | CI 与 `make verify` 对齐 | 已完成 | — | F4 附带达成 |
| ✅ F15 | 提交前 review 闸门 | 已完成 | — | AGENTS.md §9 |
| **F16** | BaseSchema 迁出 + application→api 分层守卫 | **待定** | **中** | 11 个 application 文件导入 `app.api.responses.BaseSchema`（报告原文 8 个，实际 **11 个**），属分层违规 |

### 建议执行顺序

```
F7（15min，立刻做，零依赖）
  → F6（1h，需先跑一次确认基线）
  → F16（需要重构决策，影响面大）
  → F2/F13/F8/F10/F11（按需穿插）
```

---

## P3：长期演进

### P3-1：多实例水平扩展

**现状**：[ADR-0005](file:///workspace/docs/adr/0005-single-worker-asyncio.md) 决定单 worker。消费者/调度器不重复触发。

**方向**：多容器 + Redis 分布式锁。消费者用 `XAUTOCLAIM` 抢占任务（[base_consumer.py:115](file:///workspace/backend/app/infrastructure/tasks/base_consumer.py#L115) 已有 `try_mark_processing` 钩子，就是为此准备的）。调度器用 Redis 分布式锁保证只有一个实例触发定时任务。

**ADR 需求**：新建 ADR 覆盖 ADR-0005。

### P3-2：语音 WS 编排器拆分

**现状**：[ws_handler.py](file:///workspace/backend/app/application/voice/ws_handler.py) 631 行，单文件含双向泵 + 回合提交 + 回声抑制 + 暂停监控 + ASR 重连。

**方向**：拆为多个职责类：

```
VoiceSessionController       ← 编排器（< 200 行）
  ├── AudioPump              ← 双向音频转发
  ├── TurnCommitter          ← 回合提交 + LLM 流式 + TTS
  ├── EchoSuppressor         ← 回声抑制窗口
  ├── PauseWatcher           ← 暂停超时监控
  └── AsrReconnectManager    ← ASR 重连
```

### P3-3：前端独立演进

**现状**：前端复用 Java 版本（[ADR-0014](file:///workspace/docs/adr/0014-frontend-migrated-into-python-repo.md)），[ADR-0016](file:///workspace/docs/adr/0016-testing-trophy-and-contract-conformance.md) 有契约守卫。

**方向**：长期考虑前端独立演进，codegen 契约（从 OpenAPI schema 生成 TypeScript 类型），而不是手动维护 `types/*.ts`。

---

## 版本化执行计划

### ✅ 0.9.1（P0-3，半天）

```markdown
目标：消除 @tool 壳静默返回隐患
文件：
- backend/app/graphs/tools/interview_tools.py
- backend/app/graphs/tools/rag_tools.py
- backend/app/graphs/adaptive_interview.py
验证：uv run pytest tests/graphs/test_adaptive_interview.py
```

### ✅ 0.9.2（P1-5，半天）

```markdown
目标：Agent 决策链路可观测
文件：
- backend/app/graphs/adaptive_interview.py
- backend/app/application/agent/adaptive_service.py
验证：Agent 运行后 decision_trace 不为空
```

### ✅ 0.10.0（P0-1，1-2 天）

```markdown
目标：会话状态持久化（Checkpointer）
文件：
- backend/app/application/agent/adaptive_service.py
- backend/app/application/agent/agentic_rag_service.py
- backend/app/api/deps.py
- backend/pyproject.toml
验证：重启服务后 session 仍可恢复
```

### ✅ 0.10.1（P1-3，1 天）

```markdown
目标：Agent 思考过程流式输出到前端
文件：
- backend/app/application/agent/adaptive_service.py
- backend/app/api/routers/agent_interview.py
验证：前端 SSE 收到 Agent 中间事件
```

### ✅ 0.11.0（P1-1，2-3 天）

```markdown
目标：RAG Agent 作为 ReAct Agent 的子图工具
文件：
- backend/app/graphs/rag_agent.py
- backend/app/graphs/adaptive_interview.py
- backend/app/graphs/tools/interview_tools.py
验证：Agent 在需要查资料时自动调用 RAG 子图
```

### ✅ 0.11.1（P1-2，1-2 天）

```markdown
目标：关键节点人工审批（generate_question 前）
前置：0.10.0（Checkpointer）+ 0.10.1（Streaming）
文件：
- backend/app/graphs/adaptive_interview.py
- backend/app/api/routers/agent_interview.py
- frontend/src/（审批 UI 组件）
验证：Agent 出题后暂停，等待人工确认
```

### ✅ 0.12.0（P1-4，2 天）

```markdown
目标：多 tool_calls Send fan-out 并行执行
前置：0.11.0（Subgraph 聚合）
文件：
- backend/app/graphs/adaptive_interview.py
验证：LLM 返回多 tool_calls 时并行执行
```

### ✅ 1.0.0（P0-2，1-2 天）

```markdown
目标：JWT 认证
文件：
- backend/app/api/routers/auth.py（新增）
- backend/app/infrastructure/auth/jwt.py（新增）
- backend/app/api/deps.py（加 get_current_user）
- docs/adr/0020-auth-override-adr-0007.md（新增）
验证：无 token 请求返回 `Result.code=401`（HTTP 200）
```

### P2 穿插（各版本间）

```markdown
F7（15min）：跑 pytest --cov，设 fail_under = 基线 - 2%
F6（1h）：实现 test_glossary.py，扫描 CONTEXT.md _Avoid_ 词条
F16（待定）：BaseSchema 迁出 + 分层守卫
```

---

## 风险与依赖

| 依赖 | 影响 | 缓解措施 |
|------|------|---------|
| P0-1 延迟 → P1-2/P1-3 阻塞 | 高 | Checkpointer 优先做，不做完不切到其他 P0 项 |
| P0-3 改动小但影响 `bind_tools` 签名 | 中 | 测试覆盖充分，`make verify` 验证 |
| F16 涉及 11 个文件导入 BaseSchema | 中 | 重构决策需提前，不阻塞 0.9.x 版本 |
| 前端改动（P1-2/P1-3）需前端开发环境 | 低 | ADR-0014 已保证 `pnpm dev` 全栈可跑 |