# interview-agent-py

基于 LangGraph 的智能面试官平台后端，提供简历分析、模拟面试、RAG 知识库检索等能力。

## 技术栈

- **Python 3.13** + **uv**（包管理）
- **FastAPI**（Web 框架）
- **SQLAlchemy 2.0**（async）+ **PostgreSQL** + **pgvector**（数据持久化与向量检索）
- **LangGraph**（AI Agent 编排）
- **Redis**（缓存与消息队列）
- **MinIO**（S3 兼容对象存储）
- **pytest** + **ruff** + **mypy**（测试与代码质量）
- **前端**：React 18 + TypeScript + Vite + TailwindCSS（`frontend/`，pnpm 管理）

## 快速启动

```bash
# 1. 安装后端依赖
uv sync --directory backend

# 2. 启动基础设施服务（PostgreSQL + Redis + MinIO + 自动建桶）
docker compose up -d postgres redis minio createbuckets

# 3. 验证服务连接（可选）
uv run --directory backend python scripts/check_services.py

# 4. 启动开发服务器
uv run --directory backend uvicorn app.main:app --reload
```

服务启动后访问 http://localhost:8000，API 文档见 http://localhost:8000/docs。

> 认证说明：配置 `SECRET_KEY` 后所有业务接口需携带 `Authorization: Bearer <token>`（登录见 `POST /api/auth/login`，前端登录页在 `frontend/`）；未配置 `SECRET_KEY` 时降级无认证。完整契约见 [docs/api.md](docs/api.md)。

## 前端（frontend/）

复用自 Java 版本的 React + TypeScript 前端，需 **Node ≥ 20 + pnpm**：

```bash
# 1. 安装依赖
pnpm --dir frontend install

# 2. 启动前端开发服务器（默认 http://localhost:5173）
pnpm --dir frontend dev
```

前端 dev server 将 `/api` 与 `/ws` 反向代理到 Python 后端（默认 `http://localhost:8000`，可用 `VITE_API_PROXY_TARGET` 覆盖，见 `frontend/.env.example`）。因此需同时启动后端（`uv run uvicorn app.main:app --reload`）。

## 容器化部署

```bash
# 构建后端镜像（多阶段 uv 构建，含 WeasyPrint 运行期系统库）
docker build -f backend/Dockerfile -t interview-agent-py backend

# 运行（需连通基础设施，通过 backend/.env 注入配置）
docker run --rm -p 8000:8000 --env-file backend/.env interview-agent-py
```

镜像以非 root 用户、单 worker（asyncio，ADR-0005）运行，内置 `/health` HEALTHCHECK。

## 环境变量

复制 `.env.example` 为 `.env` 并填写实际值：

```bash
cp .env.example .env
```

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 异步连接字符串 | `postgresql+asyncpg://postgres:password@localhost:5432/interview_guide` |
| `REDIS_URL` | Redis 连接字符串 | `redis://localhost:6379/0` |
| `S3_ENDPOINT` | MinIO/S3 端点 | `http://localhost:9000` |
| `S3_ACCESS_KEY` | MinIO/S3 AccessKey | `minioadmin` |
| `S3_SECRET_KEY` | MinIO/S3 SecretKey | `minioadmin` |
| `S3_BUCKET` | 存储桶名称 | `interview-guide` |
| `AI_BAILIAN_API_KEY` | LLM API Key（仅首启 DB 无 provider 时加密 seed 落库，运行时以数据库为准） | - |
| `AI_BASE_URL` | LLM API 基础 URL | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `AI_MODEL` | 默认模型 | `qwen3.5-flash` |
| `SECRET_KEY` | 应用密钥 | - |
| `APP_AI_CONFIG_ENCRYPTION_KEY` | LLM Provider API Key 加密密钥（base64 编码 32 字节，启动 seed 需要） | - |
| `AUTH_ADMIN_USERNAME` | 管理员登录用户名（与密码均配置后 login 强制校验；任一配置则必须匹配） | - |
| `AUTH_ADMIN_PASSWORD` | 管理员登录密码（同上） | - |

> 完整环境变量清单（含语音、限流、简历等配置）见 `.env.example`。

## 质量门禁

```bash
make verify     # 后端 test/typecheck/lint/format-check + 前端 lint/typecheck/test/build 一键检查
make format     # ruff 代码格式化
```

> `make verify` 现同时覆盖前后端，需本机具备 Node ≥ 20 + pnpm。

## 许可证

[AGPL-3.0](LICENSE)
