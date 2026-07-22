# 前端并入 Python 单仓：语音 WS 契约后端补齐 + 双栈门禁

ADR-0001 定「复用 Java 前端、Python API 严格兼容」，但前端源码此前仍留在 Java 仓库，Python 仓库无前端、无法独立联调交付。本次将 Java 的 React + TypeScript + Vite 前端整体搬入 Python 仓库根目录 `frontend/`，形成前后端单仓。

我们决定：**前端并入 Python 仓库，开发环境即可跑通全栈，`make verify` 同时覆盖前后端。**

- **对接点**：Vite dev 代理默认目标由 `8080`（Java）改为 `8000`（Python），并新增 `/ws` 代理（`ws: true`）转发 WebSocket。API 前缀（`/api/*`）、`Result<T>` camelCase、CORS、naive ISO 时间契约（ADR-0013）经核对一致，前端无需改动。
- **语音 WS 契约补齐（后端）**：Python 语音会话响应此前缺 `webSocketUrl`、且用 `id` 而非前端期望的 `sessionId`，导致语音面试连不上。按 ADR-0001「后端兼容前端」，给 `VoiceSessionDTO`/`VoiceSessionMetaDTO` 增补 `sessionId`（镜像 `id`），并由路由按请求 scheme/host 拼出 `webSocketUrl`（http→ws、https→wss），前端零改动。
- **双栈门禁**：`make verify` 追加 `frontend-verify`（`fe-install` → eslint → tsc --noEmit → vite build）；CI 增设 pnpm/Node20 步骤运行同一组检查；pre-commit 追加前端 eslint + tsc（不含 build，保提交速度）。代价：`make verify` 与 CI 从此依赖 Node≥20 + pnpm。
- **eslint 迁移基线**：原 Java `package.json` 缺失整个 eslint 工具链且 `eslint.config.js` 与新版插件 API 不符。本次补齐工具链、对齐 flat 配置，并将既有代码中的 `no-explicit-any`、`ban-ts-comment` 降级为 `warn`（非阻断），`no-unused-vars` 保留为 error 但遵循 `^_`/catch 约定；同时修复一处 `no-dupe-else-if` 死分支。仅编译/类型/未使用变量阻断门禁，风格类留待后续收敛。
- **包管理**：前端统一用 pnpm（`packageManager` 已锁 pnpm@10），移除冗余 `package-lock.json`。

**不变量**：前端发 `webSocketUrl`（后端按请求拼出）→ 浏览器直连后端 `/ws/voice-interview/{id}`；`make verify` 全绿 == 后端 pytest/mypy/ruff + 前端 lint/typecheck/build 全通过。

**Considered Options**：
- 前端留 Java 仓、Python 仅提供 API——**否**：无法在 Python 仓独立联调交付，违背单仓演进目标。
- 语音契约只改前端回退地址（8080→8000）——**否**：违背 ADR-0001「前端复用、后端兼容」，且 `sessionId` 缺失面更广。
- 门禁只覆盖后端 / 前端 lint 逐条修 21 处 `any`——**否**：前者不满足「双栈覆盖」诉求；后者对刚搬迁代码做大范围改写，回归风险高且超出迁移范围。
