# ADR-0019: Base 级统一启用 eager_defaults

## 状态

已接受（2026-07-27，issue #63；先例 #60）

## 背景

项目 7 个 ORM 模型的 `updated_at` 均为服务端生成列（`server_default=func.now(), onupdate=func.now()`）。
SQLAlchemy 在 UPDATE flush 后会把此类列标记过期；应用服务的惯用写法是「属性赋值 → `commit()` →
构造 DTO 返回」，commit 后读取过期列触发同步懒加载，在 asyncpg 异步上下文抛
`MissingGreenlet` → 接口 500。全局 `expire_on_commit=False` 不豁免（过期来自 flush 的
server-generated 列后置刷新，非 commit 过期）。

已两次实证：#60（语音 resume，还因此留下状态已 commit 的中间态）、#63（日程 PUT 更新与
PATCH 状态双 500）。INSERT 不受影响——SQLAlchemy 2.0 `eager_defaults="auto"` 缺省下 INSERT
在支持 RETURNING 的方言本就急取，**仅 UPDATE 需要显式 `True`**，这解释了「create 正常、
update 独炸」的不对称。

## 决策

在 `DeclarativeBase` 子类 `Base` 上统一声明 `__mapper_args__ = {"eager_defaults": True}`，
经属性继承对全部模型生效：UPDATE 语句附带 RETURNING 取回服务端生成列，commit 后属性
始终可读。#60 时加在 `VoiceInterviewSession` 上的单模型覆盖同步移除（单一事实源）。

拒绝逐模型点修：7 个模型 6 个漏配，#63 正是点修策略的漏网之鱼；该问题是 bug 类而非孤例。

配套守卫（GC loop）：`tests/test_architecture.py::test_orm_with_onupdate_columns_has_eager_defaults`
遍历 mapper registry，凡含 onupdate/server_onupdate 列的模型断言 `eager_defaults is True`，
防止新模型或单模型覆盖回归。

## 代价与取舍

- PostgreSQL + asyncpg 完整支持 RETURNING，无兼容性代价；
- UPDATE 附带 RETURNING 后失去 executemany 批量合并能力——本项目无批量 ORM 写场景，可忽略；
- 语义上与「commit 后 DTO 立即可读」的服务层惯例对齐，消除一整类隐性 500。
