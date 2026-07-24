"""日程模块 + 定时任务的真实 Postgres 端到端测试（#20 AC2 部分 + G.3 真库回归）。

跨组件：ScheduleService（应用层）→ InterviewScheduleRepository（真 SQL）→ Postgres timestamptz。
验证 G.3 边界不变量在真库成立：naive 入口挂 UTC 存储、timestamptz 读回 aware、
aware now 与 timestamptz 列比较不抛错（cancel_expired_schedules 定时任务）。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.interview_schedule.schemas import CreateScheduleRequest
from app.application.interview_schedule.service import ScheduleService
from app.domain.entities.interview_schedule import InterviewStatus
from app.infrastructure.db.models.interview_schedule import InterviewSchedule
from app.infrastructure.db.repositories.interview_schedule_repository import InterviewScheduleRepository
from app.infrastructure.scheduler.jobs import cancel_expired_schedules


def _request(interview_time: datetime) -> CreateScheduleRequest:
    return CreateScheduleRequest(company_name="阿里", position="Java 工程师", interview_time=interview_time)


async def test_create_list_roundtrip_e2e(live_session_factory: async_sessionmaker) -> None:
    """create（naive 入口挂 UTC）→ 真库 timestamptz → list → 出口无偏移序列化。"""
    async with live_session_factory() as session:
        service = ScheduleService(session=session, repository=InterviewScheduleRepository())
        dto = await service.create(_request(datetime(2099, 1, 1, 14, 0, 0)))
        assert dto.model_dump(mode="json")["interview_time"] == "2099-01-01T14:00:00"  # 出口剥偏移
        listed = await service.list_schedules(status=None, start=None, end=None)
        assert len(listed) == 1

    # 真库读回：timestamptz 列 -> aware datetime（G.3 不变量）
    async with live_session_factory() as session:
        row = (await session.execute(select(InterviewSchedule))).scalar_one()
        assert row.interview_time.tzinfo is not None
        assert row.interview_time == datetime(2099, 1, 1, 14, 0, 0, tzinfo=UTC)


async def test_list_by_range_naive_query_e2e(live_session_factory: async_sessionmaker) -> None:
    """list 过滤边界：naive start/end 经挂 UTC 后与 timestamptz 列比较不抛错、命中正确。"""
    async with live_session_factory() as session:
        service = ScheduleService(session=session, repository=InterviewScheduleRepository())
        await service.create(_request(datetime(2099, 6, 15, 10, 0, 0)))
        # naive 查询参数（模拟前端无偏移回传）
        hit = await service.list_schedules(
            status=None, start=datetime(2099, 6, 1, 0, 0, 0), end=datetime(2099, 6, 30, 0, 0, 0)
        )
        miss = await service.list_schedules(
            status=None, start=datetime(2099, 7, 1, 0, 0, 0), end=datetime(2099, 7, 31, 0, 0, 0)
        )
    assert len(hit) == 1
    assert len(miss) == 0


async def test_cancel_expired_schedules_e2e(live_session_factory: async_sessionmaker) -> None:
    """定时任务：aware now 与 timestamptz interview_time 比较，过期 PENDING -> CANCELLED。"""
    async with live_session_factory() as session:
        session.add(
            InterviewSchedule(
                company_name="c",
                position="p",
                interview_time=datetime.now(UTC) - timedelta(days=1),
                status=InterviewStatus.PENDING.value,
            )
        )
        session.add(
            InterviewSchedule(
                company_name="future",
                position="p",
                interview_time=datetime.now(UTC) + timedelta(days=1),
                status=InterviewStatus.PENDING.value,
            )
        )
        await session.commit()

    await cancel_expired_schedules(live_session_factory)

    async with live_session_factory() as session:
        rows = (
            (await session.execute(select(InterviewSchedule).order_by(InterviewSchedule.company_name))).scalars().all()
        )
    by_company = {r.company_name: r.status for r in rows}
    assert by_company["c"] == InterviewStatus.CANCELLED.value  # 过期被取消
    assert by_company["future"] == InterviewStatus.PENDING.value  # 未来保留
