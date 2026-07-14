# 不实现认证，USER 限流维度可选

Java 项目完全无认证机制（无 Auth/Interceptor/Filter）。限流 USER 维度的 `getCurrentUserId()` 依赖外部网关注入 `X-User-Id` header，无网关时无效。我们决定 Python 同样不实现认证。限流保留三维度（GLOBAL/IP/USER），但 USER 维度设为可选--无 `X-User-Id` header 时自动跳过 USER 规则，仅执行 GLOBAL + IP。裸跑时 IP 限流正常工作，有网关时 USER 限流自动生效。

**Consequences**: 任何认证/授权需由外部网关处理。Python 端只读取 `X-User-Id` header，不验证。
