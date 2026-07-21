"""APScheduler 调度框架管理器。

封装 AsyncIOScheduler，提供统一的 job 注册接口。
#18 将把其余定时任务（暂停超时检查、僵尸会话清理）汇总注册到此。
"""

import logging
from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class SchedulerManager:
    """调度框架管理器：封装 APScheduler AsyncIOScheduler。

    单 worker 部署，不会触发重复执行（ADR-0005）。
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        self._scheduler.start()
        logger.info("SchedulerManager started")

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=True)
        logger.info("SchedulerManager stopped")

    def register_job(
        self,
        func: Callable[..., Any],
        trigger: str,
        *,
        id: str,
        **kwargs: Any,
    ) -> None:
        """注册定时任务。

        Args:
            func: 要执行的函数（支持 async）。
            trigger: 触发器类型（"cron" / "interval" / "date"）。
            id: 任务唯一标识。
            **kwargs: 传递给 add_job 的额外参数（如 hour, minute, args 等）。
        """
        self._scheduler.add_job(func, trigger, id=id, **kwargs)
        logger.info("Registered scheduler job: id=%s, trigger=%s", id, trigger)

    def get_jobs(self) -> list[Any]:
        return list(self._scheduler.get_jobs())

    def remove_job(self, job_id: str) -> None:
        self._scheduler.remove_job(job_id)
        logger.info("Removed scheduler job: id=%s", job_id)
