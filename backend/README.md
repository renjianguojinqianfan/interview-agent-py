# interview-agent-py 后端

基于 LangGraph 的智能面试官平台后端（FastAPI + SQLAlchemy async + PostgreSQL/pgvector）。

前端代码在仓库根的 `frontend/`；本目录 `backend/` 存放后端全部代码与配置（DDD 分层：`app/api`、`app/application`、`app/domain`、`app/infrastructure`）。

## 常用命令（在本目录执行，或从仓库根经 `make` 执行）

```bash
uv sync                                   # 安装依赖
uv run uvicorn app.main:app --reload      # 开发服务器 -> http://localhost:8000
uv run pytest                             # 运行测试（本地自动切隔离测试库+Redis db1，首次先 make test-db-init）
uv run ruff check . && uv run mypy app/   # 规范 + 类型检查
uv run alembic upgrade head               # 数据库迁移
```

仓库根 `make verify` 一键跑通前后端质量门禁。开发约定与分层规则详见仓库根 `AGENTS.md`。
