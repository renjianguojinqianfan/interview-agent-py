from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # ADR-0019（#60/#63）：统一启用 eager_defaults——UPDATE 经 RETURNING 立即取回服务端
    # 生成列（如 onupdate 的 updated_at），避免 commit 后属性过期、asyncpg 异步上下文
    # 懒加载抛 MissingGreenlet。INSERT 在 "auto" 缺省下本就急取，此处只改变 UPDATE 行为。
    __mapper_args__ = {"eager_defaults": True}
