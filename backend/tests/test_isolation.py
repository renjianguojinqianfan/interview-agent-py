"""测试环境隔离守卫（issue #65）：本地 pytest 必须跑在独立测试库与独立 Redis db 上。

隔离由 tests/conftest.py（根级）在任何 app 模块导入前注入；本文件是防绕过的回归闸门——
一旦有人移除根 conftest 或改动派生规则导致测试直连开发库，这里立即红灯。
断言口径是"当前配置 ≠ 开发配置"（而非固定 _test 后缀），兼容显式 TEST_DATABASE_URL /
TEST_REDIS_URL 指定任意合法隔离目标（如另一实例的 db 0）。
CI 用一次性 service 容器（ci.yml 显式 env），无需隔离，守卫均 skip。
"""

import os

import pytest

from app.config.settings import settings

_IN_CI = bool(os.environ.get("CI"))


@pytest.mark.skipif(_IN_CI, reason="CI 使用一次性 service 容器，无需隔离")
def test_local_pytest_uses_isolated_database() -> None:
    """本地测试必须连隔离库，禁止 TRUNCATE 开发库。"""
    dev_url = os.environ.get("ISOLATION_DEV_DATABASE_URL")
    assert dev_url, "tests/conftest.py 的隔离注入未执行（根 conftest 被移除或绕过，issue #65）"
    assert settings.database_url != dev_url, (
        f"本地 pytest 连接了开发库 {dev_url!r}：隔离注入失效或 TEST_DATABASE_URL 被显式设成了开发库，"
        "integration/e2e 的 TRUNCATE 将清空开发库数据（issue #65）"
    )


@pytest.mark.skipif(_IN_CI, reason="CI 使用一次性 service 容器，无需隔离")
def test_local_pytest_uses_isolated_redis_db() -> None:
    """本地 Redis 必须与开发实例/db 隔离，否则测试消息会被开发 uvicorn 的 consumer 消费。"""
    dev_url = os.environ.get("ISOLATION_DEV_REDIS_URL")
    assert dev_url, "tests/conftest.py 的隔离注入未执行（根 conftest 被移除或绕过，issue #65）"
    assert settings.redis_url != dev_url, (
        f"本地 pytest 使用了开发 Redis {dev_url!r}：测试塞入的队列消息会被正在运行的 uvicorn "
        "consumer 消费并污染开发库（issue #65）"
    )
