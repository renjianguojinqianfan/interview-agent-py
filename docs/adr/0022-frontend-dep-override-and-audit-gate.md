# ADR-0022: 前端依赖安全治理——override 与审计闸门

## 状态

已接受（2026-08-06）

## 背景

v1.0beta 发版前安全扫描发现前端生产依赖存在 high 级漏洞（SEC-01/02）：

- **protobufjs**（grpc-tools 间接依赖链）存在 high 级公告（GHSA-p8p3-m333-5fcm、GHSA-h755-8qp9-pq4p 等），`pnpm audit --prod` 失败；
- **react-router-dom** 存在 high 级公告（GHSA-qwww-vcr4-c8h2：RSC 模式下的 CSRF，`>=7.12.0 <8.3.0`）；
- 额外发现 **postcss** 公告（GHSA-7hvm-4m27-m45w）。

此前仓库无任何依赖审计闸门，漏洞可静默进入发布。

## 决策

### 1. pnpm `overrides` 强制安全版本

`frontend/package.json` 增加 `pnpm.overrides`：

- `protobufjs: ^7.5.5` → 解析至 7.6.5，修复 high 公告；
- `postcss: ^8.5.23` → 修复 GHSA-7hvm-4m27-m45w。

### 2. react-router-dom 升级至修复线（部分修复）

- `react-router-dom` `^7.11.0` → `^7.14.1`，实际解析 7.18.2；
- 说明：GHSA-qwww-vcr4-c8h2 的**完整修复需 v8**，但 v8 要求 React 19.2.7+ 与 Node 22.22+，本项目为 React 18 / Node 20 且 v8 移除 `react-router-dom` 包名，升级不可行；
- 缓解论证：该公告仅影响 **RSC 模式**（React Server Components）下的 router 服务端渲染路径；本项目为纯客户端 SPA（Vite + `createBrowserRouter`），不使用 RSC，公告不适用（not-applicable）。

### 3. CI 严格 audit 闸门（`pnpm audit --prod --json`）

`.github/workflows/ci.yml` 新增 Frontend audit 步骤：

- **任何 high/critical 即失败**（严格闸门）；
- 唯一豁免 `GHSA-qwww-vcr4-c8h2`，豁免理由内联注释于 ci.yml；
- 豁免是**临时性**的：`docs/migration-plan.md` 附录 B 记为后续升级项（React 19 + Node 22 + router v8 时解除）。

### 4. 与 ADR 体系的关系

- 本 ADR 不覆盖任何既有决策，为安全治理补充；
- 依赖升级属 `package.json` 变更，按 AGENTS.md「需确认」边界经用户拍板后执行。

## 代价与取舍

- override 绕过 pnpm 的版本协商，可能引入与上游依赖的轻微不兼容（protobufjs 7.6.5 为补丁级，风险低；已跑通 vitest 57 用例 + build）；
- react-router 7.18.2 为当前 line 的修复尾部版本，与 7.11 相比 API 稳定（7.x 无破坏性变更）；
- RSC 豁免依赖「项目保持纯客户端 SPA」这一前提——若未来引入 SSR/RSC，必须立即重新评估；
- audit 仅检查 `--prod` 依赖，devDependencies 漏洞不在闸门范围（发布不携带）。
