import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.config.settings import settings
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.knowledge_base import KnowledgeBase  # noqa: F401
from app.infrastructure.db.models.llm_global_setting import LlmGlobalSetting  # noqa: F401
from app.infrastructure.db.models.llm_provider import LlmProvider  # noqa: F401
from app.infrastructure.db.models.rag_chat import RagChatMessage, RagChatSession  # noqa: F401
from app.infrastructure.db.models.resume import Resume, ResumeAnalysis  # noqa: F401
from app.infrastructure.db.models.voice_config import VoiceConfig  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
