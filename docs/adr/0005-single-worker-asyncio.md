# 单 worker + asyncio 部署

Java 用单进程 + 虚拟线程（`spring.threads.virtual.enabled: true`）处理并发。我们决定 Python 用单 worker（`uvicorn --workers 1`）+ asyncio 并发，与 Java 模型等价。这消除了多 worker 下的 Redis Stream 消费者重复消费、APScheduler 重复触发、WebSocket 跨进程通信、内存缓存不共享等一系列分布式问题。AI 应用是 I/O 密集型，asyncio 单进程足以处理并发（瓶颈在 LLM API 响应，不在 CPU）。

**Considered Options**: 单 worker（选定）/ 多 worker。多 worker 需引入分布式锁、Redis pub/sub 等协调机制，当前阶段不必要。水平扩展可后续通过多容器 + Redis 协调实现。
