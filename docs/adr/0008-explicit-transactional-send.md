# 事务后发送：显式顺序方案

Java 用 `TransactionSynchronization.afterCommit()` 确保事务提交后才发 Redis Stream 消息。我们决定用显式顺序控制：先 `await session.commit()` 提交事务，离开事务上下文后再 `await producer.send(...)` 投递消息。加降级：不在事务中时直接发送（与 Java 降级行为一致）。不用 SQLAlchemy `after_commit` 事件监听，因为 async 上下文中事件回调无法直接 await。

**Considered Options**: SQLAlchemy after_commit 事件 / 显式顺序 + 降级（选定）。事件监听在 async 下需额外处理，显式顺序更直观可控。
