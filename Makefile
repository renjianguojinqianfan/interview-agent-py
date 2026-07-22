.PHONY: verify test typecheck lint format format-check dev frontend-verify fe-install fe-lint fe-typecheck fe-build

# 一键质量门禁（前后端，推荐提交前运行）
verify: test typecheck lint format-check frontend-verify
	@echo "✔ 验证通过"

# 运行测试
test:
	uv run --frozen pytest

# 类型检查（mypy 严格模式）
typecheck:
	uv run --frozen mypy app/

# 代码规范检查
lint:
	uv run --frozen ruff check .

# 代码格式检查（不修改文件，仅校验）
format-check:
	uv run --frozen ruff format --check .

# 代码格式化
format:
	uv run --frozen ruff format .

# 开发服务器
dev:
	uv run uvicorn app.main:app --reload

# ===== 前端质量门禁（需 Node>=20 + pnpm）=====
# 安装前端依赖（锁文件驱动，保证可复现）
fe-install:
	pnpm --dir frontend install --frozen-lockfile

# 前端 lint（eslint）
fe-lint:
	pnpm --dir frontend run lint

# 前端类型检查（tsc --noEmit）
fe-typecheck:
	pnpm --dir frontend run typecheck

# 前端构建（vite build）
fe-build:
	pnpm --dir frontend run build

# 前端聚合门禁：安装 -> lint -> typecheck -> build
frontend-verify: fe-install fe-lint fe-typecheck fe-build
	@echo "✔ 前端验证通过"
