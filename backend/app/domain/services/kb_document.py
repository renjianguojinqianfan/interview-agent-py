"""知识库多文档：文档级向量化状态到 KB 级状态的聚合规则（ADR-0018，issue #52）。

KB 级 vector_status 为文档状态的聚合视图：
- 任一 FAILED -> FAILED（有失败必须显性暴露，可重触发）；
- 否则存在 PENDING/PROCESSING -> PROCESSING（仍有文档在途）；
- 否则全 COMPLETED -> COMPLETED；
- 无文档 -> PENDING（空库尚无可检索内容）。
"""

from app.domain.entities.task_status import AsyncTaskStatus


def aggregate_vector_status(statuses: list[str]) -> str:
    """聚合文档级 vector_status 列表为 KB 级状态。"""
    if not statuses:
        return AsyncTaskStatus.PENDING.value
    if AsyncTaskStatus.FAILED.value in statuses:
        return AsyncTaskStatus.FAILED.value
    if any(s in (AsyncTaskStatus.PENDING.value, AsyncTaskStatus.PROCESSING.value) for s in statuses):
        return AsyncTaskStatus.PROCESSING.value
    return AsyncTaskStatus.COMPLETED.value
