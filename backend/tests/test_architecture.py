"""架构 fitness 测试。

机械执行三条架构约束：
1. domain 层零框架依赖：禁止导入 fastapi/sqlalchemy/pydantic/langchain/redis/slowapi
   及反向依赖 app.infrastructure/app.application/app.api/app.config
2. domain 层仅允许标准库或 app.domain 内部引用
3. ADR-0008：禁止 SQLAlchemy after_commit 事件注册（async 无法 await 回调，改用显式顺序）

用 stdlib ast 解析，无需新依赖。违反即测试失败，阻止架构违规复利积累。
"""

import ast
import re
import sys
from pathlib import Path

DOMAIN_DIR = Path(__file__).resolve().parent.parent / "app" / "domain"
APP_DIR = Path(__file__).resolve().parent.parent / "app"
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

# ADR-0008：禁止注册的 SQLAlchemy 事件名（async 上下文无法 await 回调，改用显式顺序）
FORBIDDEN_EVENT_NAMES = frozenset({"after_commit"})


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


def _app_files() -> list[Path]:
    return sorted(APP_DIR.rglob("*.py"))


def _is_sqlalchemy_event_registration(node: ast.Call) -> bool:
    """判断 Call 是否为 SQLAlchemy 事件注册。

    覆盖 event.listens_for / event.listen（属性访问）与直接导入的
    listens_for / listen（裸名调用）两种写法。
    """
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in ("listens_for", "listen")
    if isinstance(func, ast.Name):
        return func.id in ("listens_for", "listen")
    return False


def _forbidden_event_name_in_call(node: ast.Call) -> str | None:
    """若事件注册 Call 含 ADR-0008 禁止的事件名，返回该名；否则 None。

    扫描位置参数与关键字参数中的字符串字面量，覆盖 listens_for(target, "after_commit")
    与 listen(target, "after_commit", fn) 两种签名。
    """
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value in FORBIDDEN_EVENT_NAMES:
            return arg.value
    for kw in node.keywords:
        kw_val = kw.value
        if isinstance(kw_val, ast.Constant) and isinstance(kw_val.value, str) and kw_val.value in FORBIDDEN_EVENT_NAMES:
            return kw_val.value
    return None


def test_no_sqlalchemy_after_commit_events() -> None:
    """ADR-0008：扫描 app/**/*.py，断言无 SQLAlchemy after_commit 事件注册。

    async 上下文中 after_commit 回调无法直接 await，ADR-0008 选定显式顺序
    （commit 后 send）+ 降级。发现 listens_for/listen 注册 after_commit 即失败。
    """
    violations: list[str] = []
    for file_path in _app_files():
        rel_path = file_path.relative_to(REPO_ROOT).as_posix()
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_sqlalchemy_event_registration(node):
                continue
            event_name = _forbidden_event_name_in_call(node)
            if event_name is not None:
                violations.append(
                    f"ADR-0008 禁止 SQLAlchemy {event_name} 事件，"
                    f"应用显式顺序（commit 后 send） - {rel_path}:{node.lineno}"
                )
    assert not violations, "发现 SQLAlchemy after_commit 事件注册：\n" + "\n".join(violations)


def test_evaluation_algorithm_not_in_application() -> None:
    """AGENTS.md §4：评估算法必须驻 domain/services，application 层只可委托不可重写。

    GC loop 防复发（F12）：R6 发现 _compute_category_scores 在 application 层重复
    domain 算法且分叉（未跳过未答题、空 category 未归一）。此测试禁止 application
    层定义名称含 'category_scores' 的函数，强制委托 domain.services.evaluation。
    """
    violations: list[str] = []
    for file_path in _app_files():
        rel_path = file_path.relative_to(REPO_ROOT).as_posix()
        if not rel_path.startswith("app/application/"):
            continue
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and "category_scores" in node.name:
                violations.append(
                    f"AGENTS.md §4：评估算法须驻 domain/services，application 不得定义 "
                    f"{node.name}（应委托 domain.services.evaluation.compute_category_scores）"
                    f" - {rel_path}:{node.lineno}"
                )
    assert not violations, "application 层存在评估算法函数（GC loop 违规）：\n" + "\n".join(violations)


# infrastructure -> application 反向依赖白名单（棘轮守卫）：
# 宿主/驱动消费者可调用 application service（见 harness plan F3 / ADR-0012）；
# pure codec/adapter 等非 service 不得反向依赖，应置于 domain/services。
INFRA_DIR = APP_DIR / "infrastructure"
INFRA_TO_APPLICATION_ALLOWLIST = frozenset(
    {
        "app.application.resume.analysis",  # ResumeAnalysisService/Result：宿主消费者调用应用服务
    }
)


def _infra_files() -> list[Path]:
    return sorted(INFRA_DIR.rglob("*.py"))


def _is_allowlisted_application_import(full: str) -> bool:
    return any(full == mod or full.startswith(mod + ".") for mod in INFRA_TO_APPLICATION_ALLOWLIST)


def test_infrastructure_imports_application_only_via_allowlist() -> None:
    """infrastructure 仅可导入白名单内 application service，禁止其他反向依赖。

    GC loop（#19 Finding 2 防复发）：question_codec 曾置于 application 且被 infrastructure
    评估消费者导入（infrastructure -> application，违反 §4），现已迁至 domain/services。
    此守卫精确拦截同类 pure-codec/adapter 反向依赖复发，同时放行宿主消费者对 application
    service 的合法调用（白名单，见 harness plan F3 / ADR-0012）。
    """
    violations: list[str] = []
    for file_path in _infra_files():
        rel_path = file_path.relative_to(REPO_ROOT).as_posix()
        for lineno, full, _top in _collect_imports(file_path):
            if not full.startswith("app.application"):
                continue
            if _is_allowlisted_application_import(full):
                continue
            violations.append(
                f"infrastructure 禁止反向依赖 application {full}"
                f"（AGENTS.md §4：pure codec/adapter 应置于 domain/services；"
                f"宿主消费者调 application service 需加入 INFRA_TO_APPLICATION_ALLOWLIST）"
                f" - {rel_path}:{lineno}"
            )
    assert not violations, "infrastructure 存在非法 application 反向依赖：\n" + "\n".join(violations)


# ADR-0016：前后端 API 契约一致性守卫（前端为权威契约、零改动 —— ADR-0001/0015）。
# 扫描 frontend/src/api/*.ts 声明的 (method, path)，断言每个都命中 FastAPI OpenAPI schema，
# 阻止「前端调用后端不存在的路由」这类契约漂移悄悄堆积（分层单测无法捕获，见 ADR-0016 病灶）。
# 方向单一：前端调用 ⊆ 后端 schema，不做后端 -> 前端 codegen（那会改写前端，违背 ADR-0001）。
FRONTEND_API_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api"

# 仅扫描 API 声明文件；request.ts（axios 封装）与 stream.ts（SSE 引擎）是 HTTP 管道，非契约声明。
_API_PLUMBING_FILES = frozenset({"request.ts", "stream.ts"})

# ADR-0015 已记录、决定「不实现」的前端死端点声明（前端无页面调用）。登记为显式白名单：
# 把散落的隐性约定升级为机器校验的登记表；清理前端死代码后应从本集合移除以收紧守卫。
FRONTEND_DEAD_ENDPOINTS_ALLOWLIST = frozenset(
    {
        "GET /api/interview/sessions/{}/report",  # interview.ts getReport
        "GET /api/resumes/health",  # resume.ts healthCheck
        "PUT /api/rag-chat/sessions/{}/knowledge-bases",  # ragChat.ts updateKnowledgeBases
        "GET /api/knowledgebase/{}",  # knowledgebase.ts getKnowledgeBase
        "GET /api/knowledgebase/uncategorized",  # knowledgebase.ts getUncategorized
        "POST /api/knowledgebase/query",  # knowledgebase.ts queryKnowledgeBase
        "POST /api/knowledgebase/query/stream",  # knowledgebase.ts queryKnowledgeBaseStream
    }
)

# request.<method>() -> HTTP 动词映射（upload 走 POST、download 走 GET）。
_REQUEST_METHOD_VERBS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "delete": "DELETE",
    "patch": "PATCH",
    "upload": "POST",
    "download": "GET",
}

_INTERP = "\x00"  # ${...} 插值占位符


def _scan_string_literal(text: str, i: int) -> tuple[str, int] | None:
    """从 text[i]（应为引号 ' \" 或 `）解析字符串/模板字面量，返回 (内容, 结束下标)。

    模板字面量中的 ${...}（含嵌套 ${}）按平衡花括号整体消费并替换为占位符 _INTERP，
    从而稳健处理 `/api/x/${id}/y` 与 `/api/x/list${q ? `?${q}` : ''}` 等嵌套写法。
    """
    if i >= len(text) or text[i] not in "'\"`":
        return None
    quote = text[i]
    i += 1
    out: list[str] = []
    while i < len(text):
        c = text[i]
        if c == "\\":
            out.append(text[i : i + 2])
            i += 2
            continue
        if quote == "`" and c == "$" and i + 1 < len(text) and text[i + 1] == "{":
            i += 1  # 移到 '{'
            depth = 0
            while i < len(text):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            out.append(_INTERP)
            continue
        if c == quote:
            i += 1
            break
        out.append(c)
        i += 1
    return "".join(out), i


def _normalize_frontend_path(raw: str) -> str:
    """把前端路径字面量归一为与 OpenAPI 对齐的形式：去查询串、路径参数 -> {}、去尾斜杠。"""
    path = raw.split("?", 1)[0]  # 去查询串（? 之后）
    path = path.replace("/" + _INTERP, "/{}")  # 作为完整路径段的 ${...} -> {}
    path = path.replace(_INTERP, "")  # 残留占位符（拼在段尾的查询后缀）丢弃
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _find_first_arg_path(text: str, open_paren: int) -> str | None:
    """从 '(' 位置起跳过空白，解析第一个字符串实参并归一为路径；非字符串实参返回 None。"""
    i = open_paren + 1
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    scanned = _scan_string_literal(text, i)
    if scanned is None:
        return None
    return _normalize_frontend_path(scanned[0])


def _extract_frontend_calls(text: str) -> set[str]:
    """从单个 .ts 文件抽取所有 「METHOD path」：request.<verb>(...) 与 streamSse({url, init.method})。"""
    calls: set[str] = set()

    for m in re.finditer(r"request\.(get|post|put|delete|patch|upload|download)\s*(?:<[^>]*>)?\s*\(", text):
        verb = _REQUEST_METHOD_VERBS[m.group(1)]
        path = _find_first_arg_path(text, m.end() - 1)
        if path and path.startswith("/api/"):
            calls.add(f"{verb} {path}")

    for m in re.finditer(r"streamSse\s*\(", text):
        window = text[m.end() : m.end() + 600]
        url_match = re.search(r"url\s*:\s*(['\"`])", window)
        if not url_match:
            continue
        scanned = _scan_string_literal(window, url_match.end() - 1)
        if scanned is None:
            continue
        path = _normalize_frontend_path(scanned[0])
        method_match = re.search(r"method\s*:\s*['\"](\w+)['\"]", window)
        verb = method_match.group(1).upper() if method_match else "GET"
        if path.startswith("/api/"):
            calls.add(f"{verb} {path}")

    return calls


def _openapi_route_set() -> set[str]:
    """从 app.main:app 的 OpenAPI schema 取全部 「METHOD path」，路径参数归一为 {}。"""
    from app.main import app

    routes: set[str] = set()
    for path, ops in app.openapi()["paths"].items():
        norm = re.sub(r"\{[^{}]+\}", "{}", path)
        if len(norm) > 1 and norm.endswith("/"):
            norm = norm[:-1]
        for method in ops:
            if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                routes.add(f"{method.upper()} {norm}")
    return routes


def test_frontend_api_calls_conform_to_openapi_schema() -> None:
    """ADR-0016：扫描 frontend/src/api/*.ts 声明的 (method, path)，断言 ⊆ 后端 OpenAPI schema。

    前端为权威契约、零改动（ADR-0001/0015）：本守卫只做单向子集校验 + 死声明白名单，
    不生成/改写前端。ADR-0015 已知的 7 处死端点登记于 FRONTEND_DEAD_ENDPOINTS_ALLOWLIST。
    新增「前端调用后端不存在的路由」即失败，阻止契约漂移复利积累（分层单测无法捕获，见 ADR-0016）。
    """
    assert FRONTEND_API_DIR.is_dir(), f"未找到前端 API 目录：{FRONTEND_API_DIR}"
    schema_routes = _openapi_route_set()

    # 白名单自紧：死端点若已被后端实现，应从白名单移除，否则守卫形同虚设。
    stale = sorted(e for e in FRONTEND_DEAD_ENDPOINTS_ALLOWLIST if e in schema_routes)
    assert not stale, "FRONTEND_DEAD_ENDPOINTS_ALLOWLIST 中的死端点已在后端实现，应移除以收紧守卫：\n" + "\n".join(
        stale
    )

    violations: list[str] = []
    for ts_file in sorted(FRONTEND_API_DIR.glob("*.ts")):
        if ts_file.name in _API_PLUMBING_FILES:
            continue
        text = ts_file.read_text(encoding="utf-8")
        for call in sorted(_extract_frontend_calls(text)):
            if call in FRONTEND_DEAD_ENDPOINTS_ALLOWLIST:
                continue
            if call not in schema_routes:
                violations.append(f"{ts_file.name}: 前端调用 `{call}` 在后端 OpenAPI schema 中不存在")

    assert not violations, (
        "前后端 API 契约漂移（ADR-0016：前端调用了后端不存在的路由；若为前端无页面调用的"
        "死声明，经确认后登记 FRONTEND_DEAD_ENDPOINTS_ALLOWLIST）：\n" + "\n".join(violations)
    )
