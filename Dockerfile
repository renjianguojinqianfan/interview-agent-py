# 智能面试官后端镜像（单 worker + asyncio，ADR-0005）。
# 多阶段构建：builder 用 uv 装依赖，runtime 仅带运行期系统库与虚拟环境。

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

# 先装依赖（利用层缓存）：仅拷贝依赖清单 + README（pyproject.readme 引用）。
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

# 再拷贝项目源码（app 为虚拟项目，无需二次安装，运行期从 WORKDIR 导入）。
COPY . .


FROM python:3.13-slim-bookworm AS runtime

# WeasyPrint（PDF 导出）运行期系统库：pango / cairo / gdk-pixbuf / 字体。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libgdk-pixbuf-2.0-0 \
        libcairo2 \
        libffi8 \
        fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 非 root 运行（安全加固）：以 --chown 拷入，避免容器内 root。
RUN useradd --create-home --uid 1000 appuser
COPY --from=builder --chown=appuser:appuser /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

# 容器健康检查：轮询 /health（对齐验收标准 /health 返回 200）。
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status == 200 else 1)"

# 单 worker：asyncio 单进程即可（ADR-0005），避免消费者/调度器重复触发。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
