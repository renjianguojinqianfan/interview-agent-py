# 复用 Java 前端，Python API 严格兼容

Java 项目已有一个完整的 React + TypeScript 前端（64 文件，12 页面），重写成本远超后端迁移本身。我们决定复用 Java 前端，Python 后端 API 契约与 Java 保持严格兼容：响应格式 `Result<T>`、字段名驼峰、错误码、SSE/WebSocket 消息协议完全对齐。代价是 Python API 层不能自由设计，必须复刻 Java 的响应结构。

**Considered Options**: 复用前端（选定）/ 重写前端 / 仅后端 API。重写前端使工期远超 7-10 周；仅后端 API 无前端验证无法交付。
