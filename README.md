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

## 快速启动

```bash
# 1. 安装依赖
uv sync

# 2. 启动基础设施服务（PostgreSQL + Redis + MinIO）
docker compose up -d

# 3. 验证服务连接（可选）
python check_services.py

# 4. 启动开发服务器
uv run uvicorn app.main:app --reload
```

服务启动后访问 http://localhost:8000，API 文档见 http://localhost:8000/docs。

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
| `AI_API_KEY` | LLM API Key | - |
| `AI_BASE_URL` | LLM API 基础 URL | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `AI_MODEL` | 默认模型 | `qwen3.5-flash` |
| `SECRET_KEY` | 应用密钥 | - |
| `APP_AI_CONFIG_ENCRYPTION_KEY` | LLM Provider API Key 加密密钥（base64 编码 32 字节，启动 seed 需要） | - |

> 完整环境变量清单（含语音、限流、简历等配置）见 `.env.example`。

## 质量门禁

```bash
make verify     # test + typecheck + lint + format-check 一键检查
make format     # ruff 代码格式化
```

## 许可证

[AGPL-3.0](LICENSE)
