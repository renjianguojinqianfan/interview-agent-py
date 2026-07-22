"""迁移链结构守卫（DB-free）。

用 stdlib ast 解析 alembic/versions/*.py 的 revision/down_revision，断言：
1. revision 全局唯一；
2. 恰好一个 base（down_revision 为 None）与一个 head（无人以其为 down_revision）；
3. 从 head 顺 down_revision 回溯可线性覆盖全部 revision（无断链/环/游离迁移）。

追加式迁移（ADR-0002）出现断链/重复 revision/多 head 会导致 `alembic upgrade head`
失败，此守卫在无数据库环境下即拦截，防止迁移链复利损坏。（结构守卫不 pin 具体
head 版本号，避免每次新增迁移都要改测试。）
"""

import ast
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _extract_revisions(file_path: Path) -> tuple[str | None, str | None]:
    """解析单个迁移文件，返回 (revision, down_revision) 字符串（缺省 None）。"""
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    revision: str | None = None
    down_revision: str | None = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign):
            target, value = node.targets[0], node.value
        else:
            continue
        if not isinstance(target, ast.Name) or value is None:
            continue
        if target.id == "revision" and isinstance(value, ast.Constant) and isinstance(value.value, str):
            revision = value.value
        elif target.id == "down_revision" and isinstance(value, ast.Constant) and isinstance(value.value, str):
            down_revision = value.value
    return revision, down_revision


def _load_chain() -> dict[str, str | None]:
    chain: dict[str, str | None] = {}
    for file_path in sorted(VERSIONS_DIR.glob("*.py")):
        revision, down_revision = _extract_revisions(file_path)
        assert revision is not None, f"迁移缺少 revision：{file_path.name}"
        assert revision not in chain, f"重复 revision：{revision}（{file_path.name}）"
        chain[revision] = down_revision
    return chain


def test_migration_chain_is_linear_with_single_head() -> None:
    chain = _load_chain()
    assert chain, "未发现任何迁移"

    bases = [rev for rev, down in chain.items() if down is None]
    downs = {down for down in chain.values() if down is not None}
    heads = [rev for rev in chain if rev not in downs]
    assert len(bases) == 1, f"应恰好一个 base（down_revision=None），实际：{bases}"
    assert len(heads) == 1, f"应恰好一个 head，实际：{heads}"

    # 从 head 顺 down_revision 回溯，须线性覆盖全部 revision（无环/无游离）。
    visited: list[str] = []
    cursor: str | None = heads[0]
    while cursor is not None:
        assert cursor in chain, f"down_revision 指向不存在的 revision：{cursor}"
        assert cursor not in visited, "迁移链存在环"
        visited.append(cursor)
        cursor = chain[cursor]
    assert set(visited) == set(chain), "存在游离迁移（未接入主链）"
