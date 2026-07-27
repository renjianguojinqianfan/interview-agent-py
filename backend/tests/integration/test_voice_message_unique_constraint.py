"""#61 竖切：voice_interview_messages (session_id, sequence_num) 唯一约束在真库真实生效。

分层单测只能证明"违约异常会被吞"，唯一约束本身是否存在于 schema 只有真 Postgres 能证明
（迁移 014 建立；缺约束时本测试红灯，防止迁移被误删/漏跑）。
基础设施不可用时按 ADR-0016 处置：CI fail / 本地 skip。
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config.settings import settings
from tests.integration.conftest import _require_infra_or_skip

_INSERT_MESSAGE = text(
    "INSERT INTO voice_interview_messages "
    "(session_id, message_type, phase, ai_generated_text, sequence_num) "
    "VALUES (:session_id, 'DIALOGUE', 'INTRO', :text, :seq)"
)


async def test_duplicate_sequence_num_rejected_by_unique_constraint() -> None:
    engine = create_async_engine(settings.database_url)
    try:
        try:
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE voice_interview_sessions RESTART IDENTITY CASCADE"))
                await conn.execute(
                    text(
                        "INSERT INTO voice_interview_sessions "
                        "(user_id, role_type, skill_id, difficulty, current_phase, status, planned_duration) "
                        "VALUES ('default', 'Java面试官', 'java-backend', 'mid', 'INTRO', 'IN_PROGRESS', 30)"
                    )
                )
        except Exception:
            _require_infra_or_skip(
                "Postgres 不可用或测试库未初始化：docker compose up -d postgres && make test-db-init"
            )

        async with engine.begin() as conn:
            await conn.execute(_INSERT_MESSAGE, {"session_id": 1, "text": "开场白", "seq": 1})

        # 同 session 同 seq 二次插入：必须被 uk_voice_interview_message_session_seq 拒绝（迁移 014）
        with pytest.raises(IntegrityError, match="uk_voice_interview_message_session_seq"):
            async with engine.begin() as conn:
                await conn.execute(_INSERT_MESSAGE, {"session_id": 1, "text": "并发开场白", "seq": 1})

        # 不同 seq 正常插入不受影响
        async with engine.begin() as conn:
            await conn.execute(_INSERT_MESSAGE, {"session_id": 1, "text": "第二问", "seq": 2})
    finally:
        await engine.dispose()
