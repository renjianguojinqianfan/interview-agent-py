"""时区策略 fitness 测试（ADR-0013：内部 aware UTC / 对外 naive）。

机械执行时区约束，阻止策略漂移（pitfall #26：横切策略无机械执行必漂移）：
1. ORM 层所有 DateTime 列必须带 timezone=True（timestamptz），禁止 naive 列。
2. 应用层禁止裸 datetime.now() 与 datetime.utcnow()，一律 datetime.now(UTC)。
3. 响应 DTO 的 datetime 字段必须带剥偏移序列化器（NaiveIsoDatetime），
   保证对外 wire format 无时区偏移（与 Java 前端契约一致）。

用 stdlib ast 静态扫描 + Pydantic 字段内省，无需新依赖。
"""

import ast
import importlib
import pkgutil
from datetime import datetime
from pathlib import Path
from typing import get_args

from pydantic import PlainSerializer

import app.application
from app.api.responses import BaseSchema

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"
MODELS_DIR = APP_DIR / "infrastructure" / "db" / "models"


def _py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _is_naive_datetime_type(type_arg: ast.expr) -> bool:
    """判断 mapped_column 的类型实参是否为 naive DateTime（违规）。

    - 裸 Name('DateTime')（未调用）-> naive -> 违规
    - Call DateTime(...) 缺 timezone=True -> 违规
    - 其他类型 -> 不涉及（False）
    """
    if isinstance(type_arg, ast.Name) and type_arg.id == "DateTime":
        return True
    if isinstance(type_arg, ast.Call) and isinstance(type_arg.func, ast.Name) and type_arg.func.id == "DateTime":
        for kw in type_arg.keywords:
            if kw.arg == "timezone" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                return False
        return True
    return False


def test_all_orm_datetime_columns_are_timezone_aware() -> None:
    """扫描 ORM 模型，断言每个 DateTime 列都带 timezone=True（ADR-0013）。"""
    violations: list[str] = []
    for file_path in _py_files(MODELS_DIR):
        rel = file_path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "mapped_column"):
                continue
            if node.args and _is_naive_datetime_type(node.args[0]):
                violations.append(f"{rel}:{node.lineno} DateTime 列须 timezone=True（ADR-0013）")
    assert not violations, "存在 naive DateTime 列：\n" + "\n".join(violations)


def test_no_naive_datetime_clock_in_app() -> None:
    """扫描 app/**，禁止裸 datetime.now() 与 datetime.utcnow()（ADR-0013：一律 datetime.now(UTC)）。"""
    violations: list[str] = []
    for file_path in _py_files(APP_DIR):
        rel = file_path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "datetime"
            ):
                continue
            if func.attr == "utcnow":
                violations.append(f"{rel}:{node.lineno} 禁止 datetime.utcnow()（用 datetime.now(UTC)，ADR-0013）")
            elif func.attr == "now" and not node.args and not node.keywords:
                violations.append(f"{rel}:{node.lineno} 禁止裸 datetime.now()（用 datetime.now(UTC)，ADR-0013）")
    assert not violations, "存在 naive 时钟调用：\n" + "\n".join(violations)


def _import_all_schema_modules() -> None:
    """导入 app.application 下所有 *schemas 模块，确保响应 DTO（BaseSchema 子类）全部注册。"""
    for mod in pkgutil.walk_packages(app.application.__path__, prefix="app.application."):
        if mod.name.rsplit(".", 1)[-1].endswith("schemas"):
            importlib.import_module(mod.name)


def _iter_subclasses(cls: type) -> list[type]:
    result: list[type] = []
    for sub in cls.__subclasses__():
        result.append(sub)
        result.extend(_iter_subclasses(sub))
    return result


def _involves_bare_datetime(annotation: object) -> bool:
    """注解是裸 datetime 或 datetime | None（未经 NaiveIsoDatetime 包装）。"""
    return annotation is datetime or datetime in get_args(annotation)


def test_response_dto_datetime_fields_strip_offset() -> None:
    """响应 DTO 的 datetime 字段必须带剥偏移序列化器（NaiveIsoDatetime，ADR-0013）。

    否则 Pydantic 对 aware datetime 输出 +00:00 偏移，破坏复用的 Java 前端契约。
    非包装的可选 NaiveIsoDatetime | None 已验证序列化仍剥偏移（字段非裸 datetime，自然跳过）。
    """
    _import_all_schema_modules()
    violations: list[str] = []
    for cls in set(_iter_subclasses(BaseSchema)):
        for field_name, field in cls.model_fields.items():
            if _involves_bare_datetime(field.annotation) and not any(
                isinstance(m, PlainSerializer) for m in field.metadata
            ):
                violations.append(f"{cls.__module__}.{cls.__name__}.{field_name}")
    assert not violations, "响应 DTO datetime 字段未用 NaiveIsoDatetime（对外会带时区偏移）：\n" + "\n".join(
        sorted(violations)
    )
