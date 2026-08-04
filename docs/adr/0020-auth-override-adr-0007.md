# ADR-0020: 引入 JWT 认证覆盖 ADR-0007 无认证决策

## 状态

已接受（2026-08-02）

## 背景

[ADR-0007](0007-no-auth-optional-user-ratelimit.md) 决定项目不实现认证，限流由外部网关处理。该决策在开发阶段合理，但项目即将进入生产环境（1.0.0），存在以下问题：

- 所有 API 端点完全开放，无任何身份校验；
- 生产部署时无法区分合法请求与恶意请求；
- 后续功能（如多用户隔离、调用配额）缺少认证基础。

## 决策

引入 JWT 认证模块，具体方案如下：

### 实现方式

> 修订（2026-08-04，#89）：按最终实现补管理员凭据与完整降级矩阵；原第 3 条“仅按 SECRET_KEY 降级”的描述已过时，以下文为准。

1. **JWT（HS256 对称签名）**：基于 `pyjwt` 库实现 token 签发与校验，密钥来源于 `settings.secret_key`，access token 24h 有效。
2. **最小化实现**：不引入 OAuth2 服务端，不做 RBAC 授权——所有登录用户同等权限，授权留待后续版本。
3. **降级矩阵**：
   - `secret_key` 为空 → 业务接口无 token 也放行，`get_current_user` 返回 `DEFAULT_USER_ID`（`"default"`）；
   - `secret_key` 配置后 → token 缺失/无效/过期一律拒绝，返回 HTTP 200 + `Result.code=401`（ADR-0003 形态），禁止降级为 default；
   - `AUTH_ADMIN_USERNAME`/`AUTH_ADMIN_PASSWORD` 均未配置 → login 降级放行（任意凭据可签发 token）；
   - 任一凭据配置 → login 必须与两者完全匹配，否则 `code=401`。
4. **端点**：
   - `POST /api/auth/login`：管理员登录，签发 24h Bearer token（`sub=default`，由 `DEFAULT_USER_ID` 常量定义）；
   - `GET /api/auth/me`：获取当前用户信息（需认证）。
5. **豁免清单**：`POST /api/auth/login`、`/health`、docs、WebSocket `/ws/voice-interview/{sessionId}` 不校验 token（REST 已全量保护，WS 握手鉴权为后续安全项）；其余业务 router 统一 `dependencies=[Depends(get_current_user)]`。

### 与 ADR-0007 的关系

- 本 ADR **覆盖** ADR-0007 的"无认证"决策，限流策略保持不变（仍由 `slowapi` 处理 GLOBAL/IP/USER 三维度）；
- JWT 认证与限流是正交关系——认证在前，限流在后；
- 外层网关仍可注入 `X-User-Id` header 覆盖用户标识，JWT 与网关可共存。

## 代价与取舍

- 引入 `pyjwt` 依赖，增加约 200KB；
- 对称签名（HS256）要求所有服务实例共享同一 `secret_key`，多实例部署需确保密钥一致；
- 当前无 refresh token 机制，access token 过期后需重新登录（24h 有效期），后续可加；
- 401 一律以 HTTP 200 + `Result.code=401` 返回（ADR-0003），前端 request 层识别 code=401 跳登录；token 存 localStorage，XSS 风险以短 token + CSP 缓解；
- 暂无用户注册/OAuth 集成，仅提供最小认证骨架；
- 部分旧端点（如登录、健康检查）无需认证，需手动标注排除。