# interview-agent-py 前端

React 18 + TypeScript + Vite + TailwindCSS 单页应用，位于仓库根 `frontend/`（复用自 Java 版本，见 ADR-0001/0014），由 pnpm 管理，需 Node ≥ 20。

## 常用命令（在 frontend/ 下执行，或经仓库根 `make fe-*`）

```bash
pnpm install                    # 安装依赖（建议 --frozen-lockfile）
pnpm dev                        # 开发服务器 -> http://localhost:5173（/api、/ws 代理到后端）
pnpm run lint                   # eslint
pnpm run typecheck              # tsc --noEmit
pnpm run test                   # vitest + jsdom + MSW 行为测试
pnpm run build                  # tsc + vite build 产物到 dist/
```

## 开发环境变量

复制 `frontend/.env.example` 为 `frontend/.env` 按需修改：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VITE_API_PROXY_TARGET` | vite dev 将 `/api`、`/ws` 代理到的后端地址 | `http://localhost:8000` |
| `VITE_API_BASE_URL` | 请求基础 URL 前缀（留空 = 同源，经代理转发） | 空 |

## 认证与登录

- 登录页 `src/pages/LoginPage.tsx`：调用 `POST /api/auth/login`，成功后 access_token 存 localStorage（`src/auth/token.ts`）。
- `src/api/request.ts` 统一注入 `Authorization: Bearer <token>`；业务接口返回 `Result.code=401` 时跳转 `/login`。
- 路由守卫 `src/components/RequireAuth.tsx`：未登录访问受保护页重定向到登录页。
- 后端未配置 `SECRET_KEY`（降级无认证）时登录页仍可用（任意账号），业务请求无需 token。

## 页面结构

`src/pages/`：LoginPage、InterviewPage、InterviewHistoryPage、InterviewSchedulePage、KnowledgeBase*、VoiceInterview*、AgentInterviewPage（SSE 流式面试 + 换题确认对话框）等；`src/api/` 为后端请求封装，`src/test/` 为 vitest + MSW 测试基建。

## 测试

行为测试断言“点按钮 -> 发对请求（MSW）-> 改对状态 -> 渲染对结果”，页面级测试位于 `src/pages/*.test.tsx`。
