"""Domain 层纯度 fitness 测试。

机械执行 AGENTS.md §4 的两条约束：
1. domain 层零框架依赖：禁止导入 fastapi/sqlalchemy/pydantic/langchain/redis/slowapi
   及反向依赖 app.infrastructure/app.application/app.api/app.config
2. domain 层仅允许标准库或 app.domain 内部引用

用 stdlib ast 解析，无需新依赖。违反即测试失败，阻止 Stage 4 起的架构违规复利积累。
"""

import ast
import sys
from pathlib import Path

DOMAIN_DIR = Path(__file__).resolve().parent.parent / "app" / "domain"
REPO_ROOT = DOMAIN_DIR.parent.parent

# 框架黑名单：domain 层禁止依赖任何框架（AGENTS.md §4: domain 层零框架依赖）
FORBIDDEN_FRAMEWORKS = frozenset(
    {
        "fastapi",
        "sqlalchemy",
        "pydantic",
        "langchain",
        "redis",
        "slowapi",
    }
)

# 跨层黑名单前缀：domain 层禁止反向依赖其他层（AGENTS.md §4: 分层依赖方向不可逆）
FORBIDDEN_INTERNAL_PREFIXES = (
    "app.infrastructure",
    "app.application",
    "app.api",
    "app.config",
)

# 允许的内部引用前缀
ALLOWED_INTERNAL_PREFIX = "app.domain"


def _domain_files() -> list[Path]:
    return sorted(DOMAIN_DIR.rglob("*.py"))


def _collect_imports(file_path: Path) -> list[tuple[int, str, str]]:
    """解析文件，返回 (行号, 完整模块名, 顶层模块名) 列表。

    相对导入（level > 0）属包内引用，跳过。
    ImportFrom 按 alias 重构完整路径（module.name），使 `from app import infrastructure`
    被跨层规则捕获、`from app import domain` 被放行，避免只看 module 而绕过。
    """
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))
    imports: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name, alias.name.split(".")[0]))
        elif isinstance(node, ast.ImportFrom):
            # 相对导入（from . import x / from .foo import y）属包内引用，跳过
            if node.level and node.level > 0:
                continue
            if node.module is None:
                continue
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                imports.append((node.lineno, full, full.split(".")[0]))
    return imports


def _check_import(lineno: int, full: str, top: str, rel_path: str) -> str | None:
    """检查单个 import 是否合规。合规返回 None，违规返回 actionable 描述。"""
    if top in FORBIDDEN_FRAMEWORKS:
        return f"domain 层禁止导入框架 {top}（AGENTS.md §4: domain 层零框架依赖） - {rel_path}:{lineno}"
    if full.startswith(FORBIDDEN_INTERNAL_PREFIXES):
        return f"domain 层禁止反向依赖其他层 {full}（AGENTS.md §4: 分层依赖方向不可逆） - {rel_path}:{lineno}"
    if top in sys.stdlib_module_names:
        return None
    if full.startswith(ALLOWED_INTERNAL_PREFIX):
        return None
    return (
        f"domain 层仅允许标准库或 app.domain 内部引用，禁止导入 {full}"
        f"（AGENTS.md §4: domain 层零框架依赖） - {rel_path}:{lineno}"
    )


def test_domain_layer_is_pure() -> None:
    """扫描 app/domain/**/*.py 所有 import，断言零框架依赖、零跨层依赖。"""
    violations: list[str] = []
    for file_path in _domain_files():
        rel_path = file_path.relative_to(REPO_ROOT).as_posix()
        for lineno, full, top in _collect_imports(file_path):
            msg = _check_import(lineno, full, top, rel_path)
            if msg is not None:
                violations.append(msg)
    assert not violations, "domain 层存在违规 import：\n" + "\n".join(violations)
