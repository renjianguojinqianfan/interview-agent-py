from enum import Enum


class AsyncTaskStatus(Enum):
    """异步任务状态机，复用于简历分析、知识库向量化、语音评估等异步流程。

    生命周期：PENDING -> PROCESSING -> COMPLETED / FAILED
    """

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
