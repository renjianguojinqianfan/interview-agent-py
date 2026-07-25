"""迁移 012 真库往返测试（issue #41）：upgrade head -> downgrade 011 -> upgrade head。

结构守卫（tests/test_migration_chain.py）只校验链形态，无法发现 downgrade 遗漏
drop 或 upgrade 与 ORM 不一致。本测试对真 Postgres 执行完整往返，并断言 012 交付
的三块 schema（题库表 / 知识库生成状态列族 / 会话来源列）真实存在。
与其余集成竖切同惯例：CI 缺基础设施 fail、本地无 docker 优雅 skip。
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.config.settings import settings
from tests.integration.conftest import _require_infra_or_skip

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


@dataclass(frozen=True)
class SchemaFacts:
    """012 相关的 schema 事实：题库表列型、CHECK 约束、索引、知识库列、会话新列默认值。"""

    question_columns: dict[str, str]
    check_constraints: set[str]
    indexes: set[str]
    kb_columns: set[str]
    session_defaults: dict[str, str | None]


async def _fetch_schema_facts() -> SchemaFacts:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            question_columns = {
                row[0]: row[1]
                for row in await conn.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_name = 'knowledge_base_questions'"
                    )
                )
            }
            check_constraints = {
                row[0]
                for row in await conn.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.table_constraints "
                        "WHERE constraint_type = 'CHECK' "
                        "AND table_name IN ('knowledge_base_questions', 'knowledge_bases')"
                    )
                )
            }
            indexes = {
                row[0]
                for row in await conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename IN ('knowledge_base_questions', 'knowledge_bases')"
                    )
                )
            }
            kb_columns = {
                row[0]
                for row in await conn.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name = 'knowledge_bases'")
                )
            }
            session_defaults = {
                row[0]: row[1]
                for row in await conn.execute(
                    text(
                        "SELECT column_name, column_default FROM information_schema.columns "
                        "WHERE table_name = 'interview_sessions' "
                        "AND column_name IN ('source_type', 'knowledge_base_id', 'interview_category')"
                    )
                )
            }
        return SchemaFacts(
            question_columns=question_columns,
            check_constraints=check_constraints,
            indexes=indexes,
            kb_columns=kb_columns,
            session_defaults=session_defaults,
        )
    finally:
        await engine.dispose()


def test_migration_012_roundtrip_and_schema() -> None:
    cfg = _alembic_config()
    try:
        command.upgrade(cfg, "head")
    except Exception:
        _require_infra_or_skip("Postgres 不可用或未迁移：docker compose up -d postgres && uv run alembic upgrade head")

    # 往返：降到 011（012 全部对象应被回收），再升回 head
    command.downgrade(cfg, "011")
    after_downgrade = asyncio.run(_fetch_schema_facts())
    assert after_downgrade.question_columns == {}, "downgrade 后题库表应不存在"
    assert "question_gen_status" not in after_downgrade.kb_columns
    assert after_downgrade.session_defaults == {}, "downgrade 后会话来源列应不存在"

    command.upgrade(cfg, "head")
    facts = asyncio.run(_fetch_schema_facts())

    # 1. 题库表：列集完整 + timestamptz 时间列（ADR-0013）
    expected_columns = {
        "id",
        "knowledge_base_id",
        "skill_id",
        "difficulty",
        "type",
        "category",
        "question",
        "topic_summary",
        "reference_answer",
        "key_points_json",
        "scoring_rubric",
        "follow_ups_json",
        "source_context",
        "kb_content_hash",
        "status",
        "created_at",
        "updated_at",
    }
    assert set(facts.question_columns) == expected_columns
    assert facts.question_columns["created_at"] == "timestamp with time zone"
    assert facts.question_columns["updated_at"] == "timestamp with time zone"

    # 2. CHECK 约束与索引
    assert "knowledge_base_questions_status_check" in facts.check_constraints
    assert "knowledge_bases_question_gen_status_check" in facts.check_constraints
    assert {
        "idx_kb_question_kb_status",
        "idx_kb_question_skill_difficulty",
        "idx_kb_question_gen_status_updated",
    } <= facts.indexes

    # 3. 知识库生成状态列族 + 会话来源列（source_type 默认 NORMAL）
    assert {
        "question_gen_status",
        "question_gen_error",
        "question_gen_task_id",
        "question_gen_config",
        "question_gen_message",
        "question_gen_saved_count",
        "question_gen_skipped_count",
        "question_gen_updated_at",
    } <= facts.kb_columns
    assert set(facts.session_defaults) == {"source_type", "knowledge_base_id", "interview_category"}
    assert "NORMAL" in (facts.session_defaults["source_type"] or "")
