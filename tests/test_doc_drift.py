"""文档漂移检测测试（F5）。

扫描 docs/**/*.md 中反引号包裹的文件路径引用，断言路径在 repo 中存在。
捕获文档引用已删除/重命名文件导致的漂移（如 pitfalls.md 记录的 api/errors.py 事件：
删除 re-export shim 后 docs 多处引用漂移，直到手动检查才发现）。

判别规则（精确）：反引号内容须同时满足
1. 含 / （路径分隔符，排除裸文件名与代码标识符如 asyncio.gather()）
2. 以已知扩展名结尾（.py/.md/.yml/.lua/.toml/.sql/.json/.ts 等）
3. 不含特殊字符 * ? { } = < > 空格 且非 URL/锚点/家目录

解析基：repo 根 / app/ / docs/ / tests/ / 文档所在目录，任一存在即合法。
KNOWN_MISSING 为已登记的计划未建/历史引用，文件创建后应移除以使守卫重新生效。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

KNOWN_EXTENSIONS = (
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".sql",
    ".json",
    ".cfg",
    ".ini",
    ".lua",
    ".ttf",
    ".ts",
    ".j2",
    ".st",
)

# 已知故意引用不存在文件的路径（计划未建 / 历史记录）。
# 文件创建后应从此集合移除，使守卫重新生效。
KNOWN_MISSING: frozenset[str] = frozenset(
    {
        # 计划未建 - 后续阶段交付
        "app/skills/opening.yml",  # Stage 7 开场问题配置
        "domain/entities/knowledgebase.py",  # Stage 5.2 领域实体
        "domain/entities/resume.py",  # Stage 3.2 领域实体
        "infrastructure/redis/rate_limit.lua",  # 限流脚本（实际改用 Python rate_limit.py）
        "infrastructure/voice/asr.py",  # Stage 7B.2 ASR 服务
        "infrastructure/voice/tts.py",  # Stage 7B.3 TTS 服务
        # harness 计划项 - F2/F3/F6/F13
        "docs/adr/0010-infrastructure-consumer-application-dependency.md",  # F3
        "docs/agents/harness-coverage.md",  # F13
        "docs/rejected-ideas.md",  # F2
        "tests/test_glossary.py",  # F6
        # 历史记录 - pitfalls.md 描述已删除/重命名的文件
        "api/errors.py",  # 已删除的 re-export shim
        "app/api/errors.py",  # 已删除的 re-export shim
        "app/application/resume/grading.py",  # 已重命名（GradingService 词汇表违规）
        "docs/review-r1-r2-fix-plan.md",  # 已删除的临时修复计划
    }
)

_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_EXCLUDE_CHARS = set("*?{}=<> ")


def _is_path_candidate(text: str) -> bool:
    """判断反引号内容是否为文件路径候选：含 /、以已知扩展名结尾、无特殊字符。"""
    if "/" not in text or not text.endswith(KNOWN_EXTENSIONS):
        return False
    if text[0] in "/~" or "://" in text:
        return False
    return not any(c in _EXCLUDE_CHARS for c in text)


def _exists_anywhere(candidate: str, doc_path: Path) -> bool:
    """在多个解析基下检查路径是否存在：repo 根 / app/ / docs/ / tests/ / 文档所在目录。"""
    bases = [
        REPO_ROOT / candidate,
        REPO_ROOT / "app" / candidate,
        REPO_ROOT / "docs" / candidate,
        REPO_ROOT / "tests" / candidate,
        doc_path.parent / candidate,
    ]
    return any(b.exists() for b in bases)


def test_no_dead_file_references_in_docs() -> None:
    """扫描 docs/**/*.md 反引号文件路径，断言无死引用（除 KNOWN_MISSING 外）。"""
    violations: list[str] = []
    for doc in DOCS_DIR.rglob("*.md"):
        text = doc.read_text(encoding="utf-8")
        for match in _BACKTICK_RE.findall(text):
            if not _is_path_candidate(match):
                continue
            if match in KNOWN_MISSING:
                continue
            if not _exists_anywhere(match, doc):
                rel_doc = doc.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel_doc} 引用了不存在的文件路径: {match}")
    assert not violations, "文档存在死引用（文件已删除/重命名/未建但未登记 KNOWN_MISSING）：\n" + "\n".join(violations)
