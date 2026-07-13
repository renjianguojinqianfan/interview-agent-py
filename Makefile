.PHONY: verify test typecheck lint format dev

# 一键质量门禁（推荐提交前运行）
verify: test typecheck lint
	@echo "✔ 验证通过"

# 运行测试
test:
	uv run pytest

# 类型检查（mypy 严格模式）
typecheck:
	uv run mypy app/

# 代码规范检查
lint:
	uv run ruff check .

# 代码格式化
format:
	uv run ruff format .

# 开发服务器
dev:
	uv run uvicorn app.main:app --reload
