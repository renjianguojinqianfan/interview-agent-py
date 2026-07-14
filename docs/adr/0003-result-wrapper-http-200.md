# Result<T> 统一 HTTP 200 + 成功码 200

Java 所有 HTTP 响应（含业务错误）统一返回 HTTP 200，用 body 中 `code` 字段区分成功/失败。成功码是 **200**（`CommonConstants.StatusCode.SUCCESS = 200`，非 0），业务错误码 2001-11011。前端 `request.ts` 的 `SUCCESS_CODE = 200` 和响应拦截器依赖此格式。我们决定严格复刻此模式，通过 FastAPI 全局异常处理器实现。流式场景（SSE/WebSocket）不使用 Result 包装，用协议原生格式传递数据和错误。

**Consequences**: 放弃 RESTful HTTP 状态码语义，所有错误都是 HTTP 200。FastAPI 的 404（路由不存在）和 422（验证错误）需被全局异常处理器覆盖，转为 Result 格式。
