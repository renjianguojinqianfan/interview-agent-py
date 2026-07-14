# 全新空库，Alembic 独立管理

Java 用 Hibernate `ddl-auto: update` 自动建表，无版本化迁移脚本，schema 是代码生成的副产品。我们决定 Python 从全新空库开始，用 Alembic 独立设计和管理 schema，不迁就 Hibernate 生成的表结构（蛇形表名、外键命名等）。Java 项目无生产数据需要保留，因此无需数据迁移。

**Considered Options**: 兼容 Java schema / 全新空库（选定）。兼容 Hibernate schema 会让 SQLAlchemy 模型扭曲以匹配 Hibernate 命名习惯，不值得。
