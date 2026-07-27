"""pytest 根 conftest（issue #65）：本地测试环境隔离注入。

必须在任何 app 模块导入之前生效——app/infrastructure/db/session.py 的 engine 在模块导入时
就固化了 settings.database_url，因此这里的模块级代码是唯一可靠的注入点（pytest 保证
根 conftest 先于所有测试模块导入）。

规则：
- CI（存在 CI 环境变量）：不干预，ci.yml 的一次性 service 容器原样使用；
- 本地：DB 切到 TEST_DATABASE_URL（缺省按库名追加 _test 派生），Redis 切到
  TEST_REDIS_URL（缺省按 db 号 +1 派生）——开发库零触碰、测试消息不会被开发
  uvicorn 的 consumer 消费，跑全量测试无需停后端。

派生规则与 scripts/init_test_db.py 保持同一约定（改动需两处同步）；
防绕过守卫见 tests/test_isolation.py。测试库初始化：make test-db-init。
"""

import os
from urllib.parse import urlparse, urlunparse

from app.config.settings import settings


def _derive_test_database_url(url: str) -> str:
    """库名追加 _test：postgresql+asyncpg://…/interview_guide -> …/interview_guide_test。"""
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/")
    if not db_name or db_name.endswith("_test"):
        return url
    return urlunparse(parsed._replace(path=f"/{db_name}_test"))


def _derive_test_redis_url(url: str) -> str:
    """Redis db 号 +1：redis://host:6379/0 -> redis://host:6379/1。"""
    parsed = urlparse(url)
    db = int(parsed.path.lstrip("/") or "0")
    return urlunparse(parsed._replace(path=f"/{db + 1}"))


if not os.environ.get("CI"):
    # 注入前记录开发配置原值，供 tests/test_isolation.py 守卫断言"当前配置 ≠ 开发配置"
    os.environ["ISOLATION_DEV_DATABASE_URL"] = settings.database_url
    os.environ["ISOLATION_DEV_REDIS_URL"] = settings.redis_url
    settings.database_url = os.environ.get("TEST_DATABASE_URL") or _derive_test_database_url(settings.database_url)
    settings.redis_url = os.environ.get("TEST_REDIS_URL") or _derive_test_redis_url(settings.redis_url)
