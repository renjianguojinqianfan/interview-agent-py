"""初始化本地隔离测试库（issue #65）：make test-db-init。

幂等可反复跑：测试库不存在则创建 -> 确保 pgvector extension -> alembic upgrade head。
测试库名从 settings.database_url 按"库名追加 _test"派生，与 tests/conftest.py 的
隔离注入保持同一约定（改动需两处同步）。新迁移合入后重跑本脚本即可同步测试库 schema。
"""

import asyncio
import os
import subprocess
import sys
from urllib.parse import urlparse, urlunparse

import asyncpg

from app.config.settings import settings

# 强制 UTF-8 输出（Windows GBK 终端乱码防护，与 check_services.py 同法）
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def _derive_test_database_url(url: str) -> str:
    """库名追加 _test（与 tests/conftest.py 同约定）。"""
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/")
    if not db_name or db_name.endswith("_test"):
        return url
    return urlunparse(parsed._replace(path=f"/{db_name}_test"))


def _asyncpg_dsn(url: str, db_name: str | None = None) -> str:
    """SQLAlchemy URL -> asyncpg DSN（去掉 +asyncpg 方言标记，可选替换库名）。"""
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
    if db_name is not None:
        parsed = parsed._replace(path=f"/{db_name}")
    return urlunparse(parsed)


async def _ensure_database(test_url: str) -> None:
    test_db = urlparse(test_url).path.lstrip("/")
    admin = await asyncpg.connect(_asyncpg_dsn(test_url, "postgres"))
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", test_db)
        if not exists:
            # CREATE DATABASE 不能参数化；库名来自本仓库派生规则/本地环境变量，转义双引号防注入
            safe_db = test_db.replace('"', '""')
            await admin.execute(f'CREATE DATABASE "{safe_db}"')
            print(f"已创建测试库 {test_db}")
        else:
            print(f"测试库 {test_db} 已存在")
    finally:
        await admin.close()

    conn = await asyncpg.connect(_asyncpg_dsn(test_url))
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        print("pgvector extension 就绪")
    finally:
        await conn.close()


def _run_migrations(test_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": test_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    if result.returncode != 0:
        raise SystemExit("alembic upgrade head 失败")
    print("测试库迁移完成")


def main() -> None:
    # 与 tests/conftest.py 同优先级：显式 TEST_DATABASE_URL > 按库名追加 _test 派生
    test_url = os.environ.get("TEST_DATABASE_URL") or _derive_test_database_url(settings.database_url)
    if test_url == settings.database_url:
        raise SystemExit(
            f"测试库 URL 与开发库相同（{settings.database_url}），拒绝初始化：请检查 TEST_DATABASE_URL 或库名派生"
        )
    asyncio.run(_ensure_database(test_url))
    _run_migrations(test_url)
    print(f"测试环境就绪：{urlparse(test_url).path.lstrip('/')}（本地 pytest 将自动使用，无需停 uvicorn）")


if __name__ == "__main__":
    main()
